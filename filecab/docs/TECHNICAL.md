# Filecab — technical reference

Discord-native DOJ document filing for the GATVRP community. Members pick a
document type, answer questions one at a time over DM, and the answers are
rendered into a finished HTML document.

## Architecture

- `filecab/filecab.py` — the `Filecab` cog: Config schema, the `on_message`
  DM router, persistent-view re-registration, and the `filecab` command group
  (`setup`, `settings`, `templates`).
- `filecab/template_manager.py` — `TemplateManager` loads HTML+JSON template
  pairs from `<cog_data_path>/templates/` and renders them.
- `filecab/filing.py` — `FilingManager` runs the DM Q&A flow, posts pending
  filings to the staff review forum, and finalizes/publishes on approval.
- `filecab/publisher.py` — `DocumentPublisher`, the seam to the external
  GitHub Pages documents site. **Currently a stub** — see below.
- `filecab/views.py` — all `discord.ui.View`/`Modal` classes: the setup
  wizard, the persistent document-type select panel, the persistent
  Approve/Deny review view, and the settings panel.

## Template format

Each document type is a pair of files dropped into
`<cog_data_path>/templates/` — no code changes needed to add a new one:

- `<slug>.json` — the spec:
  ```json
  {
    "template": "subpoena.html",
    "output_dir": "subpoenas",
    "name": "Subpoena",
    "fields": [
      {"key": "defendant_name", "prompt": "What is the defendant's full name?"},
      {"key": "case_number", "prompt": "What is the case number?"}
    ]
  }
  ```
- `<slug>.html` (named by `"template"` above) — the HTML facsimile of the
  source document, with `{{field_key}}` placeholders matching each field's
  `"key"`. Placeholders are substituted with plain regex — not a full
  templating engine — to keep the bot's runtime footprint light. Unmatched
  placeholders are left as-is rather than erroring.

After dropping in a new pair, run `filecab settings` → **Reload Templates**
(or `filecab templates`) to pick it up without restarting the bot, then
**Repost Panel** so it appears in the select menu.

## Filing flow

1. A member picks a document type from the persistent select panel
   (`TemplateSelectView`), posted in the guild's configured document channel.
2. The bot DMs one question per field in sequence (`FilingManager.start_filing`
   / `handle_reply`). Replying `cancel` aborts at any point.
3. On completion, the answers are rendered into the template's HTML and saved
   locally under `<cog_data_path>/documents/<output_dir>/<slug>-<user_id>-<ts>.html`.
4. If `approval_required` is on (default), a Q&A transcript + Approve/Deny
   buttons are posted to the review forum (`FilingReviewView`); otherwise the
   document is finalized immediately.
5. On approval (or when approval isn't required), `FilingManager._finalize`
   calls `DocumentPublisher.publish()` and posts the result to the document
   channel.

## Publishing — not yet wired up

`DocumentPublisher.publish()` and `.unpublish()` currently return `None` /
`False` — no GitHub push happens yet. Until that's implemented, finalized
documents are announced in the document channel as a local file attachment
with a note that site publishing isn't configured. The intended design (per
project planning) is a GitHub Contents API call over `aiohttp` using a token
stored via Red's shared API tokens, rather than a local git clone + subprocess
push, to keep the bot's runtime lightweight. Wiring this up just means
filling in those two methods — no other call site needs to change.

## Config schema

- **Guild**: `document_channel`, `document_review_forum`, `approval_required`,
  `approval_role`, `panel_message_id`, `published_documents` (dict of
  `doc_id` → `{slug, output_dir, filename, user_id, status, thread_id?, message_id?}`,
  used for persistent-view re-registration and the takedown command).
- **User**: `active_filing` (`{"slug", "guild_id", "field_index", "answers"}`),
  the in-progress DM Q&A state.
