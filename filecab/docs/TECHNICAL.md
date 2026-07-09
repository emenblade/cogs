# Filecab — technical reference

Discord-native DOJ document filing for the GATVRP community. Members pick a
document type, answer questions one at a time over DM, and the answers are
rendered into a finished HTML document, published to `emenblade/lcrpfilecab`
once staff sign off.

## Architecture

- `filecab.py` — the `Filecab` cog: Config schema, the `on_message` router
  (DMs during filing, plus logging review-thread conversation), persistent-
  view re-registration, and the `filecab` command group (`setup`, `settings`,
  `file`, `templates`, `refresh`).
- `github_client.py` — `GitHubClient`, a thin `aiohttp` wrapper around the
  GitHub REST API (list/get/put/delete file contents). Token comes from
  Red's own shared API tokens (`[p]set api github token,<token>`), not
  anything collected by the cog itself.
- `template_manager.py` — `TemplateManager` loads HTML+JSON template pairs
  from `<cog_data_path>/templates/` and classifies fields. Populated by
  fetching from the configured site repo (`refresh_from_repo`, exposed as
  `filecab refresh`) — see `docs/SITE_REPO_CONTRACT.md` for the schema that
  repo's `templates/` folder must follow.
- `filing.py` — `FilingManager` runs the DM Q&A flow, mints filing ids, posts
  pending filings to a private review thread, handles approve/deny, and
  publishes/takes down on explicit staff action.
- `publisher.py` — `DocumentPublisher`, pushes/removes filings on the
  configured site repo via `GitHubClient`.
- `views.py` — all `discord.ui.View`/`Modal` classes: the setup wizard
  (including the site-repo step), the persistent document-type select panel,
  the staff `file` command's select, the persistent review view (dynamic
  Assign buttons + Approve/Deny), the persistent signer-handoff DM view
  (Sign/Decline), the persistent post-approval "Make Public" view, and the
  settings panel (including template access gating and document
  takedown/delete).

## UI conventions

All buttons across `views.py` follow one color/emoji scheme, so a new button
should match rather than invent its own:

- **Green** — confirm / positive / completed (`Confirm` in the setup wizard,
  `✅ Approve`, `✅ Sign`, a signer's `✅ {label}: signed` state, `✅ Published`
  once Make Public succeeds).
- **Red** — destructive / negative outcome (`❌ Deny`, `❌ Decline`,
  `❌ Delete Permanently`, `❌ Confirm Delete`, a declined signer's
  `🔁 Reassign {label}` state).
- **Blurple** — a primary, non-destructive action (`Set Site Repository`,
  `🔄 Reload Templates`, `🔄 Refresh Templates from Repo`, `Change Site Repo`,
  `Repost Panel`, `🌐 Make Public`, an unassigned signer's `➕ Assign {label}`
  state).
- **Grey** — secondary / navigational / "opens another menu" (`Cancel`,
  `Skip for Now`, `Template Access`, `Manage Documents`, `Open to Everyone`,
  `🗑️ Take Down`, a pending signer's `⏳ {label}: awaiting reply` state).

`Cancel` is always grey, never red — red is reserved for an action that
actually denies/declines/deletes something, and using it for a plain abort
would dilute that signal. Emoji are reserved for buttons that represent a
concrete document/filing action with a natural icon (approve, deny, sign,
decline, publish, delete, take down, (re)assign) or that match an emoji
their own result message already uses (`🔄` on the two template-refresh
buttons, matching their own "🔄 Reloaded…"/"🔄 Fetched…" replies); generic
navigation/admin buttons (`Confirm`, `Cancel`, `Change Site Repo`, `Template
Access`, `Manage Documents`, …) stay plain text.

## Template format

See **`docs/SITE_REPO_CONTRACT.md`** for the full, formal schema (this is the
contract whoever maintains the templates/site repo must follow — the field
schema including `signers[]` and `fill_at`, the filings sidecar shape, etc.).
Summary: each document type is a pair of files in the configured site repo's
`templates/` folder — `<template_id>.json` (manifest) + the HTML file it
names in `"html_file"`, with `{{field_key}}` placeholders substituted via
plain regex (`utils.render_template`), not a full templating engine, to keep
the bot's runtime footprint light. `filecab refresh` fetches them; no code
changes are needed to add a new document type, just add the pair to the repo
and refresh.

### Field semantics

- **`filled_by`**: `"applicant"` (the citizen filer), `"auto"` (the bot
  computes it — always today's date in every template seen so far), or
  `"judge"` (a staff/judge value).
- **`prompt`**: if non-null, the field is asked over DM during the filing
  session (`TemplateManager.prompted_fields`) — this covers `applicant`
  fields *and* `judge` fields on judge-authored templates (see below), with
  one rule. If `prompt` is `null`, the field is never asked in the DM flow.
- **`fill_at`** (only meaningful on `"auto"` fields): `"submission"` fields
  are computed the moment the DM Q&A finishes; `"approval"` fields are
  computed when a staff member approves. There's no way to tell these apart
  from `filled_by` alone, so it's an explicit, hand-set key — get it right
  when authoring a new template rather than relying on field position.
- **Judge fields with `prompt: null`** (`TemplateManager.approval_judge_fields`)
  are collected from the *approving staff member*, not the filer, via a modal
  shown when they click Approve. Every template seen so far has at most 2 of
  these (fits comfortably in Discord's 5-field modal limit).
- **Judge-authored templates** (`TemplateManager.is_staff_authored` — true
  when no field has `filled_by: "applicant"`, e.g. Order to Release, Warrant
  of Execution) have no citizen role at all: a judge/staff member fills the
  *entire* DM Q&A themselves (their `judge` fields have real prompts). These
  are excluded from the public document panel and only reachable via the
  `filecab file` staff command.
- **Multi-signer handoff**: a template's top-level `"signers"` array lists
  every party role (`{role, label, requires_handoff, name_field?}`).
  `applicant` and `judge` always have `requires_handoff: false` (unchanged
  mechanics above). Other roles (`party_one`, `witness`, `counsel`, ...) have
  `requires_handoff: true` and their own `filled_by`-tagged field(s)
  (`TemplateManager.signer_fields`) — always `prompt: null`, collected from
  whichever *Discord member staff assign* to that role, not the filer. See
  "Filing lifecycle" below for the assign → DM sign/decline flow. **Known
  gap**: `divorce.json`'s `signing_party` role reuses a field
  (`signing_party_name`) that also has a real prompt asked of the filer
  during the original Q&A — so the filer's answer gets silently overwritten
  once the assigned signer signs. Every other template seen so far avoids
  this by giving the handoff field a distinct `<role>_signature` key with
  `prompt: null`. Also, `divorce.json`'s `counsel` role is only actually
  applicable if `counsel_name` isn't "None" — there's currently no schema way
  to mark a signer role conditional/not-applicable, so assigning nobody to an
  inapplicable role would block Approve forever. Both need a template-side
  fix (or a bot-side "N/A" override button, not yet built) before Divorce's
  handoff flow is fully correct — flagged to the user rather than guessed
  around.

After adding a new pair to the site repo, run `filecab refresh` to fetch it
without restarting the bot, then **Repost Panel** (settings) so citizen-facing
ones appear in the select menu. `filecab templates`/settings' **Reload
Templates** re-scan what's already on disk locally, with no network call.

### Filing access gates

Per-template role restrictions live entirely on the cog side (guild
`template_access`, see Config schema below) rather than in the template
schema itself — the site repo stays a pure content source, and every
template still appears together in the one document-select dropdown (the
panel is a single persistent message, so options can't vary per viewer
anyway). The gate is enforced where selection turns into DM Q&A
(`views._start_filing_from_select`): if the template has any allowed roles
configured and the selecting member has none of them (and isn't an admin),
they get an ephemeral "you don't have permission" reply instead of a DM.
`filecab file` (`StaffFileSelectView`) always passes `enforce_gate=False` —
that command is already staff/admin-only, so the gate would be redundant
there. Settings → **Template Access** manages the mapping: pick a template,
then either select role(s) via a `RoleSelect` (replaces the set) or hit
**Open to Everyone** to clear it back to unrestricted. Only citizen-facing
templates are offered — gating a staff-authored one would be dead
configuration, since `filecab file` always bypasses the gate.

`SettingsPanelView` and `StaffFileSelectView` both override
`interaction_check` to re-validate staff/admin on every click, matching the
per-click checks the review-thread views already used. This matters because
`filecab_settings`/`filecab_file` send their view via `ctx.send(...,
ephemeral=True)`, and Red's hybrid commands silently drop `ephemeral` when
invoked with a text prefix instead of a slash command — without the
re-check, a prefix invocation would leave the settings panel (with its
permanent-delete and access-reconfiguration actions) visible and clickable
to any member, and would let anyone reach `filecab file`'s
`enforce_gate=False` path and bypass template gates entirely.

## Filing lifecycle

Every filing — citizen-filed or judge-authored — always requires staff
approval, and approving only creates the paper trail; publishing to the
public site is a separate, explicit step, so e.g. a warrant isn't visible
before police have acted on it. Approve itself stays disabled until every
handoff signer role has signed.

1. **DM Q&A completes** → `"submission"` auto fields are filled with today's
   date → a `filing_id` (`<template_id>-<year>-<seq>`, from the global
   per-template-per-year counter in `filing_counters`) is minted → the
   filing's `signers` map is seeded (one `{user_id: null, status:
   "unassigned", dm_message_id: null}` entry per handoff role) → a **private**
   thread is created in the configured review channel with the Q&A
   transcript and `FilingReviewView` (one "➕ Assign X" button per handoff
   role, plus Approve/Deny), and the filer is added to it directly
   (`Thread.add_user`, `invitable=False` so only staff with Manage Messages
   can add anyone else) — they can see and post in their own filing's
   thread, like a support ticket, but have no access to any other filing's
   thread; that isolation is Discord's own private-thread membership model,
   not something the bot enforces. Status: `pending`. Nothing is rendered
   yet.
2. **Assign** (staff click "➕ Assign Witness" etc.) → permission-checked, then
   an ephemeral `UserSelect` — no @-mention typing, since DMs can't resolve
   mentions — picking a member calls `FilingManager.assign_signer`, which DMs
   them the transcript + a persistent `SignerRequestView` (Sign/Decline),
   sets that role's `status: "pending"`, and rebuilds the review message
   (button becomes a disabled "⏳ waiting on @user").
3. **Sign** → a modal (reusing the same pattern as judge sign-off) collects
   that role's field(s); `FilingManager.sign` merges the answer into the
   filing and sets `status: "signed"` — once every handoff role reads
   `signed`, Approve unlocks. **Decline** → `status: "declined"`, the review
   message shows "🔁 Reassign X" so staff can pick someone else; the filing
   stays open rather than dying.
4. **Approve** → if the template has approval-time judge fields, a modal
   collects them; `"approval"` auto fields are filled with today's date;
   the full answer set (applicant + signer + judge) is rendered and both
   `documents/<template_id>/<filing_id>.html` and a sidecar `.json` are saved
   locally (`TemplateManager.save_document`/`save_sidecar`). The thread's
   view is swapped to `ApprovedDocumentView` (a persistent "🌐 Make Public"
   button). Status: `approved` — on file, not public yet.
5. **Deny** → notifies the filer and disables any signer DM requests still
   awaiting a reply, so nobody can sign a dead filing. Status: `denied`.
6. **Make Public** (separate, whenever staff are ready) → calls
   `DocumentPublisher.publish()` (stub) and announces in the document
   channel; on success the button relabels to a disabled, green
   "✅ Published" (matching the "completed" color used elsewhere) and stays
   that way permanently — see "Persistence & restart safety" for why it
   doesn't need re-registration after a restart. Status: `published`.
7. **Take Down** (settings panel → Manage Documents → a filing → 🗑️ Take
   Down) → deletes the local files, calls `unpublish()` if it was live.
   Status: `removed`. The record itself is kept (title, answers, audit
   trail) — only the rendered/live copies are gone.
8. **Delete Permanently** (settings panel → Manage Documents → a filing →
   ❌ Delete Permanently → ❌ Confirm Delete) → same cleanup as Take Down if the
   filing was still `approved`/`published`, then erases the guild config
   record entirely (`FilingManager.purge`). Irreversible; gated behind an
   extra confirmation step since it drops the stored answers for good.
   Pending filings aren't eligible (deny it first) so an open review thread
   never loses the record it's referencing. Manage Documents lists every
   non-`pending` filing (any status), not just published ones, so denied or
   already-taken-down filings can be purged too.

Throughout all of the above, staff and the filer can talk directly in the
filing's private thread — there's no dedicated "ask a question" button,
it's just a normal Discord conversation once the filer's been added.
`Filecab.on_message` picks up every human message posted there (matched by
`thread.parent_id` == the configured review channel, then `thread_id` on
the filing record) via `FilingManager.log_thread_message`, and appends it to
that filing's `discussion` list in config — a durable copy of the
conversation that outlives the thread itself if it's later archived or the
channel is reconfigured.

## Persistence & restart safety

Discord buttons/selects stop working after a process restart unless the bot
re-registers a matching view (same custom IDs) against the still-live
message before anyone clicks them again — `discord.py` doesn't remember
views across restarts on its own. Exactly four views in this cog are
long-lived enough to need that: `TemplateSelectView` (the document panel),
`FilingReviewView` (review-thread post), `SignerRequestView` (DM'd to a
handoff signer), and `ApprovedDocumentView` (post-approval "Make Public").
Everything else — the setup wizard, the settings panel and everything it
opens (Template Access, Manage Documents, and their sub-views),
`StaffFileSelectView` — has a finite timeout and is expected to just go
stale on restart like any short-lived admin flow; that's fine, nothing is
lost since they don't hold state a citizen is waiting on.

`Filecab.initialize()` calls `_register_persistent_views()` on every cog
load (including after a restart), which walks every guild's
`published_documents` and re-adds the right view for each message still
worth re-registering:

- Panel select → re-added whenever `panel_message_id` is set and at least
  one citizen-facing template is currently loaded (if none are — e.g. the
  site repo is unreachable at boot — the already-posted panel's dropdown
  stays unresponsive until templates are available again and the panel is
  reposted; there's no way to populate a select with zero options).
- `pending` filings → `FilingReviewView`. If the filing's template was since
  deleted from the site repo, `spec` comes back `None`; the view still
  re-registers, but Approve is force-disabled with an explanatory
  "⚠️ Template Missing" label (there's no schema left to safely collect
  judge fields or rebuild Assign buttons) while Deny stays fully
  functional, so staff can still clean up an orphaned filing instead of it
  being permanently stuck with dead buttons.
- `approved` filings → `ApprovedDocumentView`.
- `published` filings → nothing. Once Make Public succeeds the button is
  edited to a permanently disabled "✅ Published" — that state is baked
  into the message itself, so there's nothing left to re-register.
- Any signer whose handoff is still `status: "pending"` → `SignerRequestView`
  on their DM, regardless of the parent filing's own status (a pending
  signer only ever exists while the filing itself is still `pending`).

## Publishing

`DocumentPublisher.publish()`/`.unpublish()` push/remove
`filings/<template_id>/<filing_id>.html` + its sidecar `.json` (see
`docs/SITE_REPO_CONTRACT.md`) on the configured site repo's branch, via
`GitHubClient` (GitHub Contents API over `aiohttp`, no local git clone or
subprocess — keeps the bot's runtime lightweight). Reads (template fetching)
work without a token against a public repo; writes always need one, set via
Red's own `[p]set api github token,<token>` (bot owner only) — not collected
by the cog itself. If no token is configured, `publish()`/`unpublish()`
return `None`/`False` rather than raising, and callers already handle that
(e.g. announcing the file locally instead of linking a live URL). The site's
own GitHub Action rebuilds `filings-index.json`/`index.html` automatically on
that push — filecab doesn't maintain any index itself.

## Config schema

- **Guild**: `document_channel`, `document_review_channel` (a text channel —
  each filing gets its own private thread inside it, see "Filing lifecycle"),
  `approval_role`, `panel_message_id`, `published_documents` (dict of
  `filing_id` → `{template_id, title, category, user_id, answers, filed_date,
  status, thread_id?, message_id?, signers, discussion, approved_by?,
  signed_date?, signed_by?, html_path?, json_path?, published_url?}`, used
  for persistent-view re-registration and the takedown command). `signers`
  is itself a dict of `role` → `{user_id, status, dm_message_id}` (`status`
  ∈ `unassigned | pending | signed | declined`), one entry per
  handoff-required signer role. `discussion` is a list of `{author_id,
  author_label, content, at}`, one entry per human message posted in the
  filing's private review thread. `template_access` (dict of `template_id`
  → `[role_id, ...]`; a template missing from this dict, or mapped to an
  empty list, is open to everyone — see "Filing access gates" above).
- **User**: `active_filing` (`{"template_id", "guild_id", "field_index",
  "answers"}`), the in-progress DM Q&A state.
- **Global**: `filing_counters` (`{"<template_id>-<year>": int}`, backing the
  `filing_id` scheme); `site_repo` (`"owner/repo"`, serves as both the
  templates source and publish destination), `site_branch` (default
  `"main"`), `site_base_url` (optional override, else computed as
  `https://{owner}.github.io/{repo}`).
