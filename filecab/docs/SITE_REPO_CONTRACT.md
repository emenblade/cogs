# Site repo contract

Filecab points at **one GitHub repo** (`filecab setup` step 4, or `filecab settings` →
**Change Site Repo**) that serves **two roles at once**, matching the structure
`emenblade/lcrpfilecab` already uses:

1. **Templates source** — `filecab refresh` fetches every `templates/*.json` +
   its paired `.html` from this repo's `templates/` folder over the GitHub API.
2. **Publish destination** — approved filings get pushed to this same repo's
   `filings/` folder.

This doc is the formal spec of what that repo's layout and file schemas must
look like for the bot to work correctly. It's aimed at whoever maintains the
templates/site repo (a person or another Claude session), not at filecab's own
code — see `docs/TECHNICAL.md` for the bot's internals.

## `templates/<template_id>.json`

```json
{
  "template_id": "name_change",
  "title": "Change of Name Request",
  "source_doc": "[LCRP] DOJ Name Change",
  "html_file": "name_change.html",
  "category": "Civil & Family",
  "index_fields": ["current_name", "requested_name"],
  "signers": [
    {"role": "applicant", "label": "Filer", "requires_handoff": false},
    {"role": "party_one", "label": "Party One", "requires_handoff": true, "name_field": "party_one_name"},
    {"role": "judge", "label": "Approving Judge", "requires_handoff": false,
     "note": "Filled automatically at approval — not part of the intake handoff flow."}
  ],
  "fields": [
    {"key": "current_name", "label": "Current Name", "prompt": "What is your current legal name?",
     "type": "string", "required": true, "filled_by": "applicant"},
    {"key": "date_filed", "label": "Date of Application", "prompt": null,
     "type": "date", "required": true, "filled_by": "auto", "fill_at": "submission"},
    {"key": "party_one_signature", "label": "Party One's Signature", "prompt": null,
     "type": "signature", "required": true, "filled_by": "party_one"},
    {"key": "approving_judge_name", "label": "Approving Judiciary", "prompt": null,
     "type": "signature", "required": true, "filled_by": "judge"},
    {"key": "approval_date", "label": "Date", "prompt": null,
     "type": "date", "required": true, "filled_by": "auto", "fill_at": "approval"}
  ]
}
```

**Required top-level keys**: `template_id` (must match the filename), `title`,
`html_file`, `category`, `index_fields` (a list of field keys surfaced in the
site's search index), `signers`, `fields`.

**`signers[]`** — the full roster of who's involved:
- `role` — a short slug. `applicant` (the filer) and `judge` (collected from
  the approving staff member at approval time, via a modal) are always
  present with `requires_handoff: false` — the bot has built-in handling for
  both and expects those exact role names.
- `label` — human-readable, shown on buttons/prompts.
- `requires_handoff` — `true` means this role needs a **real Discord member**
  assigned to it (via a `UserSelect` on the review post) who then gets DM'd a
  Sign/Decline request. `false` means no handoff — either `applicant`/`judge`,
  or a role fully handled within the original filer's own DM Q&A (see
  Order to Release / Warrant of Execution: a judge fills the *entire* form
  themselves, so every field — including their own — has a real `prompt` and
  `requires_handoff: false`).
- `name_field` — for `requires_handoff: true` roles, the field key that
  already holds this person's name (asked earlier of the filer, purely for
  display when staff pick who to assign — not authentication).

**`fields[]`** — one entry per rendered `{{token}}`:
- `key` — must match a `{{key}}` placeholder in the paired HTML file, and vice
  versa (every field must be used, every token must have a field).
- `label` — shown on buttons/transcripts/modals.
- `prompt` — **the field that decides when it's asked**: non-null means it's
  asked over DM during the original filing session, regardless of
  `filled_by`. `null` means it's never asked in the DM Q&A — it's filled
  automatically (`auto`) or collected later from someone else (`judge` at
  approval time, or a `requires_handoff` role's assigned signer).
- `type` — `string` | `text` (multi-line) | `date` | `signature` | `choice`
  (informational only — the bot doesn't currently validate or restrict the
  DM reply against `options` for a `choice` field, it's asked as free text
  like any other type; the HTML itself controls cursive rendering via CSS
  class for `signature`). `options` (a list of strings) is conventionally
  paired with `choice` and mentioned in the prompt text itself, but nothing
  in the bot enforces it yet.
- `required` — whether an empty/skippable answer is allowed.
- `filled_by` — `applicant`, `auto`, `judge`, or any `role` declared in
  `signers[]` with `requires_handoff: true`. Every non-`auto` value must match
  a declared signer role.
- `fill_at` (**required whenever `filled_by` is `"auto"`**) — `"submission"`
  (filled the moment the DM Q&A finishes) or `"approval"` (filled when staff
  approve). There's no way to infer this from field position or naming —
  it must be set explicitly on every auto field.
- `depends_on` (optional) — `{"field": key, "equals": value}`. When present,
  this field is only asked over DM if the referenced field's answer equals
  `value` exactly; `key` must refer to an earlier field in the same
  `fields[]` array (one the filer will have already answered, or that was
  itself skipped, by the time this one's turn comes up — dependencies
  can chain, e.g. field C depending on field B which itself depends on
  field A). When the condition isn't met, the field is skipped entirely —
  never asked — and auto-filled with `skip_value` instead.
- `skip_value` (used together with `depends_on`) — the value recorded for
  this field when it's skipped. Falls back to an empty string if omitted on
  a conditional field.
- `note` (optional) — free text, not read by the bot; useful context for
  whoever edits the template next.

## `templates/<template_id>.html`

The rendered facsimile, referenced by `html_file`. `{{key}}` placeholders are
substituted via plain regex (not a templating engine) — every field's `key`
must appear exactly once as `{{key}}` somewhere in the HTML.

## `templates/<template_id>.png` (optional)

A blank preview image of the document — e.g. a screenshot of the rendered
HTML with no fields filled in. Purely cosmetic and entirely optional: if
present, the bot sends it (with a short "here's what this looks like"
message) when someone starts filing the template, when a handoff signer is
asked to sign, and in the filing's review channel; if absent, none of those
messages get sent — filecab never errors or warns about a missing one.
Fetched by filename convention (`<template_id>.png`), not referenced from
the `.json` manifest.

## `filings/<template_id>/<filing_id>.html` + `.json`

Written by the bot on approval (`.html`) and on **Make Public** (both files
pushed to this repo). `<filing_id>` is `<template_id>-<year>-<seq>`. The
sidecar `.json`:

```json
{
  "filing_id": "name_change-2026-0001",
  "template_id": "name_change",
  "title": "Change of Name Request",
  "category": "Civil & Family",
  "html_file": "name_change/name_change-2026-0001.html",
  "filed_date": "2026-07-07",
  "signed_date": "2026-07-08",
  "signed_by": "Cassius Hale",
  "index_values": {"current_name": "Marcus Webb", "requested_name": "Marcus Sterling"}
}
```

## Auto-indexing

If the repo has `scripts/build_index.py` + a GitHub Action that runs it on
push to `filings/**` or `templates/*.json` (as `emenblade/lcrpfilecab` does),
the public `filings-index.json`/`index.html` stay up to date automatically —
filecab's publisher only pushes the two files above and relies entirely on
that existing Action. Filecab does not maintain any index itself.
