# Filecab — technical reference

Discord-native DOJ document filing for the GATVRP community. Members pick a
document type, answer questions one at a time over DM, and the answers are
rendered into a finished HTML document, published to `emenblade/lcrpfilecab`
once staff sign off.

## Architecture

- `filecab.py` — the `Filecab` cog: Config schema, the `on_message` router
  (DMs during filing, plus logging review-channel conversation), persistent-
  view re-registration, and the `filecab` command group (`setup`, `settings`,
  `file`, `templates`, `refresh`, `nuke`).
- `github_client.py` — `GitHubClient`, a thin `aiohttp` wrapper around the
  GitHub REST API (list/get/put/delete file contents, plus a raw-bytes fetch
  for the optional preview image). Token comes from Red's own shared API
  tokens (`[p]set api github token,<token>`), not anything collected by the
  cog itself.
- `template_manager.py` — `TemplateManager` loads HTML+JSON template pairs
  from `<cog_data_path>/templates/` and classifies fields. Populated by
  fetching from the configured site repo (`refresh_from_repo`, exposed as
  `filecab refresh`) — see `docs/SITE_REPO_CONTRACT.md` for the schema that
  repo's `templates/` folder must follow. Also opportunistically fetches
  each template's optional `<template_id>.png` preview image the same way.
- `filing.py` — `FilingManager` runs the DM Q&A flow, mints filing ids, posts
  pending filings to a private review channel, handles approve/deny, lets
  anyone with channel access edit a field (staff can additionally add
  people to the channel), publishes/takes down on explicit staff action,
  and optionally archives+deletes a channel once its filing is published.
- `publisher.py` — `DocumentPublisher`, pushes/removes filings on the
  configured site repo via `GitHubClient`.
- `views.py` — all `discord.ui.View`/`Modal` classes: the setup wizard
  (including the site-repo step), the persistent document-type select panel,
  the staff `file` command's select, the persistent review view (dynamic
  Assign buttons + Approve/Deny/Edit Field/Add Person), the persistent
  signer-handoff DM view (Sign/Decline), the persistent post-approval
  "Make Public" view, and the settings panel (including template access
  gating, document takedown/delete, and the optional log forum).

## UI conventions

All buttons across `views.py` follow one color/emoji scheme, so a new button
should match rather than invent its own:

- **Green** — confirm / positive / completed (`Confirm` in the setup wizard,
  `✅ Approve`, `✅ Sign`, a signer's `✅ {label}: signed` state, `✅ Published`
  once Make Public succeeds).
- **Red** — destructive / negative outcome, or a signer state that needs
  re-engagement (`❌ Deny`, `❌ Decline`, `❌ Delete Permanently`,
  `❌ Confirm Delete`, a declined signer's `🔁 Reassign {label}` state, a
  stale signer's `🔁 Re-sign Needed: {label}` state).
- **Blurple** — a primary, non-destructive action (`Set Site Repository`,
  `🔄 Reload Templates`, `🔄 Refresh Templates from Repo`, `Change Site Repo`,
  `Repost Panel`, `🌐 Make Public`, `✏️ Edit Field`, `👤 Add Person`, an
  unassigned signer's `➕ Assign {label}` state).
- **Grey** — secondary / navigational / "opens another menu" (`Cancel`,
  `Skip for Now`, `Template Access`, `Manage Documents`, `📋 Log Forum`,
  `Open to Everyone`, `🗑️ Take Down`, a pending signer's
  `⏳ {label}: awaiting reply` state).

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
- **`depends_on`/`skip_value`** (optional, on any `prompt`-ed field):
  `TemplateManager.field_applies`/`advance_past_skipped` check the
  referenced earlier field's answer against `depends_on.equals` every time
  the DM Q&A is about to move to the next question (`FilingManager.
  start_filing` for a leading run of skippable fields, `handle_reply` after
  every answer) — if it doesn't match, the field is auto-filled with
  `skip_value` and never asked, and the check repeats for the next field
  too, so a whole run of dependent fields (B depends on A, C depends on B,
  ...) resolves in one pass once their common trigger is known. Since a
  dependency is only ever resolved against answers already given (or
  already skipped), this works for arbitrarily deep condition chains
  without knowing anything about fields further down the form. Question
  numbers ("Question N of Total") use the *fixed* total prompted-field
  count, not a recount of what'll actually be asked — so skipped questions
  can make the visible number jump (e.g. 12 → 14), which is expected, not
  a bug.
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
per-click checks the review-channel views already used. This matters because
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

If a template has an optional preview image (`templates/<template_id>.png`
— see `docs/SITE_REPO_CONTRACT.md`), `TemplateManager.preview_image_path`
is checked at every point someone's about to see the document for the first
time — starting the DM Q&A, being asked to sign, and the review channel's
opening post — and the image is sent alongside a short explanatory message
if it's there. Purely cosmetic: if there's no image, none of those checks
send anything extra, no error or placeholder.

1. **DM Q&A completes** → `"submission"` auto fields are filled with today's
   date → a `filing_id` (`<template_id>-<year>-<seq>`, from the global
   per-template-per-year counter in `filing_counters`) is minted → the
   filing's `signers` map is seeded (one `{user_id: null, status:
   "unassigned", dm_message_id: null}` entry per handoff role) → a **private
   text channel** is created under the configured review category, with
   (optionally) the preview image, then the Q&A transcript and
   `FilingReviewView` (one "➕ Assign X" button per handoff role, plus
   Approve/Deny). The channel is created with an explicit permission
   overwrite granting the filer `view_channel`/`send_messages` on just that
   one channel — the same mechanism the `forms` cog's ticket channels
   already use, **not threads**. An earlier version of this used a private
   thread with `Thread.add_user`, which turned out not to reliably grant
   access no matter what permission the bot had (confirmed against a real
   server, including a manual add attempt by the server owner) — threads
   just don't behave like an independent per-member ACL the way a channel's
   own permission overwrites do, so this now creates a real channel instead.
   `_post_review` handles two distinct failure points, neither of which can
   silently drop the filing (the citizen's already been told in
   `handle_reply` that it was submitted, before this even runs): if
   `category.create_text_channel()` itself fails (most likely the bot's
   role missing **Manage Channels**/**Manage Roles** on the category —
   needed to create a channel there with a custom overwrite at all), there's
   no channel to fall back to, so it just tells the filer and saves the
   record with `channel_id`/`message_id` left unset; if something fails
   *after* the channel exists (posting the transcript, etc.), the channel
   itself already has the right permissions for staff to see it, so the
   fallback error message goes straight into it instead. Either way the
   record is always saved regardless of the outcome. Status: `pending`.
   Nothing is rendered yet.
2. **Assign** (staff click "➕ Assign Witness" etc.) → permission-checked, then
   an ephemeral `UserSelect` — no @-mention typing, since DMs can't resolve
   mentions — picking a member calls `FilingManager.assign_signer`, which
   tries to DM them (optionally) the preview image, then the transcript + a
   persistent `SignerRequestView` (Sign/Decline). **DM can fail even for
   someone who was DM'd successfully earlier in the same filing** — the
   filer's own initial Q&A DM went out as a direct response to *their own*
   interaction (picking a template from the panel), which gets a Discord
   exception to the "allow DMs from server members" privacy setting; this
   DM doesn't, since staff picked the signer, not the signer themselves. On
   `discord.Forbidden`, `assign_signer` falls back to granting the signer
   access to the filing's review channel (same mechanism as Add Person) and
   posting the same `SignerRequestView` there instead — its Sign/Decline
   buttons just edit whichever message they're attached to, so nothing
   about them needed to change. Either way, sets that role's
   `status: "pending"` and rebuilds the review message (button becomes a
   disabled "⏳ waiting on @user"). Returns which path was used (`"dm"` /
   `"channel"` / `None` if both failed, e.g. no review channel to fall back
   to either) so staff get an accurate confirmation message rather than a
   flat success/failure.
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
   locally (`TemplateManager.save_document`/`save_sidecar`). The channel's
   view is swapped to `ApprovedDocumentView` (a persistent "🌐 Make Public"
   button). Status: `approved` — on file, not public yet.
5. **Deny** → notifies the filer and disables any signer DM requests still
   awaiting a reply, so nobody can sign a dead filing. Status: `denied`.
   Also archives and closes the review channel — see "Archiving & channel
   cleanup" below; a denied filing has no other path to Make Public, so
   this is the only cleanup it ever gets.
6. **Make Public** (separate, whenever staff are ready) → calls
   `DocumentPublisher.publish()` (stub) and announces in the document
   channel; on success the button relabels to a disabled, green
   "✅ Published" (matching the "completed" color used elsewhere) and stays
   that way permanently — see "Persistence & restart safety" for why it
   doesn't need re-registration after a restart. Status: `published`. Also
   kicks off archiving the review channel — see "Archiving & channel
   cleanup" below.
7. **Take Down** (settings panel → Manage Documents → a filing → 🗑️ Take
   Down) → deletes the local files, calls `unpublish()` if it was live.
   Status: `removed`. The record itself is kept (title, answers, audit
   trail) — only the rendered/live copies are gone.
8. **Delete Permanently** (settings panel → Manage Documents → a filing →
   ❌ Delete Permanently → ❌ Confirm Delete) → same cleanup as Take Down if the
   filing was still `approved`/`published`, then erases the guild config
   record entirely (`FilingManager.purge`). Irreversible; gated behind an
   extra confirmation step since it drops the stored answers for good.
   Pending filings aren't eligible (deny it first) so an open review channel
   never loses the record it's referencing. Manage Documents lists every
   non-`pending` filing (any status), not just published ones, so denied or
   already-taken-down filings can be purged too.

Throughout all of the above, staff and the filer can talk directly in the
filing's private channel — there's no dedicated "ask a question" button,
it's just a normal Discord conversation once the filer's channel exists.
`Filecab.on_message` picks up every human message posted there (matched by
`channel.category_id` == the configured review category, then `channel_id`
on the filing record) via `FilingManager.log_review_message`, and appends
it to that filing's `discussion` list in config — a durable copy of the
conversation that outlives the channel itself if it's later deleted.

While a filing is `pending`, `FilingReviewView` also carries two buttons
beyond Approve/Deny/Assign:

- **✏️ Edit Field** (`FilingManager.edit_field`) — deliberately *not*
  staff-gated, unlike every other button on this view; anyone with access to
  the channel (the filer included) can fix a wrong answer. Only fields with
  `filled_by: "applicant"` are offered — judge/signer fields already have
  their own consent-gated flows (the approval modal, the sign-off DM), and
  a generic edit button reaching into those would undermine them. If any
  handoff signer has already signed, picking a field shows a warning first
  ("editing this will invalidate their signature") before the modal opens;
  confirming resets every currently-`signed` signer to a new `stale` status
  (Approve stays locked the same way it does for `declined` — `approve()`
  already requires every signer to read exactly `signed`) and posts a
  `~~old~~ → **new**` notice in the channel. Reuses the *existing*
  Assign/Sign machinery to get a fresh signature rather than inventing a
  parallel one: `_assign_button_appearance` just needed one more branch
  (`stale` → red `🔁 Re-sign Needed: {label}`, enabled), and
  `assign_signer`/`sign` don't care what the signer's prior status was.
- **👤 Add Person** (`FilingManager.add_person_to_channel`) — staff-gated,
  unlike Edit Field. Grants an extra Discord member `view_channel`/
  `send_messages`/`read_message_history` on that one channel via a plain
  `channel.set_permissions` overwrite — the same mechanism the filer
  themselves was added with in step 1, not tracked anywhere in config since
  Discord persists the overwrite on its own.

## Archiving & channel cleanup

Entirely optional (`document_log_forum` unset by default) — without it,
review channels just accumulate the way they always have. Configured via
settings → **📋 Log Forum**, which is its own button opening a dedicated
ephemeral select rather than a row on `SettingsPanelView` itself, since
that panel is already at Discord's 5-row cap. The mechanism directly
mirrors `forms/tickets.py`'s `close_ticket` — same shape, same
`archived=True, locked=True` call, same >2000-char "post the truncated
body, then attach the full thing as a `.txt` file" fallback that cog's own
history discovered was necessary — with one bot-side permission
requirement in common: whatever your `forms` ticket-log forum already
needs to lock its own archived posts, this one needs too.

Both ways a filing can leave `pending` — **Approve → Make Public** or
**Deny** — funnel through the same `FilingManager._close_channel`, so
every filing gets the same cleanup regardless of which way it ends; a
denied filing was never able to get archived/closed at all before this
existed, since nothing short of Make Public ever touched the channel.

- **Deny** calls `_close_channel` immediately (synchronously, no delay —
  there's no site rebuild to wait for) with a plain `"❌ **{title}** —
  denied"` summary line. `views.FilingReviewView.deny` disables its own
  buttons and edits the review message *before* calling
  `FilingManager.deny`, since that call may delete the very channel the
  interaction is happening in — anything that still needs the message or
  channel to exist has to happen first, and anything after is wrapped to
  fail silently rather than crash the interaction.
- **Make Public** schedules `_announce_and_close` as a background task
  (`PUBLISH_ANNOUNCE_DELAY_SECONDS` — the site's GitHub Action needs time
  to finish rebuilding, so neither the announcement nor the archive fires
  against a link that still 404s). Once that delay elapses it announces the
  live link in the channel **and DMs it to the filer directly** — so they
  still have it even if they never revisit a channel that's about to be
  archived away — then hands off to `_close_channel` with `"📄
  **{title}**\n{url}"` (or a "not published live" note if publishing isn't
  configured) as the summary line.

`_close_channel` itself:

1. If no log forum is configured, or it's not actually a forum channel,
   stop — the review channel is left alone, same as if this feature didn't
   exist. No silent data loss either way.
2. `_archive_to_log` pulls the channel's *entire* message history
   (`channel.history(limit=None, oldest_first=True)` — everything: the
   original transcript, discussion, edit notices, sign confirmations, not
   just the initial Q&A dump `_build_transcript` produces for the review
   post) via `utils.build_channel_transcript`, and downloads every
   attachment before the channel that hosts them is gone. A new forum post
   goes up, tagged by `record["category"]` if set
   (`utils.get_or_create_forum_tag`, creating the tag on first use — same
   as `forms`): **message 1** is the caller's `summary_line`; **message 2**
   is the transcript, truncated to 2000 chars with the full text attached
   as a `.txt` file if it ran over (exactly `forms`' fallback, for exactly
   the reason it exists there — a real channel's history routinely exceeds
   Discord's message limit); any attachments follow in their own
   message(s), 10 per batch (Discord's per-message cap). The post is then
   `thread.edit(archived=True, locked=True)` — closed, read-only, done. The
   resulting thread id is saved back to the filing's record as
   `archived_thread_id`.
3. Only once that whole sequence has succeeded does `_close_channel` delete
   the original channel. If archiving raises partway through, the channel
   is deliberately **not** deleted, and `archived_thread_id` is never
   persisted either — better a channel that should've been cleaned up
   stays around than one that's actually lost.

## Nuke — wiping test data

`filecab nuke` (`FilingManager.wipe_guild_data`) is a bot-owner-only
(`@commands.is_owner()`, distinct from every other command in this cog which
gates on the guild's approval role/admin) escape hatch for resetting a test
server to a clean slate before going live — not part of the normal filing
lifecycle. It posts a summary (record/channel/thread counts pulled live from
Discord and config) and waits up to 60 seconds via `bot.wait_for("message",
...)` for a chat reply matching the confirmation password (`"canada"`,
matched case-insensitively/trimmed) from the invoking user in the same
channel; anything else, or no reply in time, cancels with nothing touched.

On confirmation, `wipe_guild_data`:

1. Deletes every local `documents/<template_id>/<filing_id>.{html,json}` file
   for every record in the guild's `published_documents`, and calls
   `DocumentPublisher.unpublish()` for any that were `status: "published"`
   (removing their GitHub `filings/` copies too) — mirrors `takedown`'s own
   cleanup, just for every record at once.
2. Clears `published_documents` back to `{}`.
3. Deletes **every** channel actually found in the configured review category
   (`category.channels`, not just ones with a tracked record) — catches
   orphaned test channels from crashed/incomplete filings too.
4. Deletes **every** thread actually found in the configured log forum, both
   active (`forum.threads`) and archived (`async for ... in
   forum.archived_threads(limit=None)`).
5. Resets the global `filing_counters` to `{}` — bot-wide, not guild-scoped,
   since counters aren't tracked per-guild; the confirmation embed calls this
   out explicitly so it's never a silent side effect.

Templates (`templates_path`, `template_access`) and every other guild
setting (`document_channel`, `document_review_category`, `document_log_forum`,
`approval_role`, `panel_message_id`, site repo config) are untouched — only
user-filed data and its two review-artifact channels/threads are in scope.
Per-item failures (a channel/thread that fails to delete) are counted
separately and reported back rather than aborting the whole wipe.

## Persistence & restart safety

Discord buttons/selects stop working after a process restart unless the bot
re-registers a matching view (same custom IDs) against the still-live
message before anyone clicks them again — `discord.py` doesn't remember
views across restarts on its own. Exactly four views in this cog are
long-lived enough to need that: `TemplateSelectView` (the document panel),
`FilingReviewView` (review-channel post), `SignerRequestView` (DM'd to a
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

- **Guild**: `document_channel`, `document_review_category` (a **category** —
  each filing gets its own private text channel created under it, see
  "Filing lifecycle"), `document_log_forum` (optional — a forum channel;
  see "Archiving & channel cleanup"), `approval_role`, `panel_message_id`,
  `published_documents` (dict of `filing_id` → `{template_id, title,
  category, user_id, answers, filed_date, status, channel_id?, message_id?,
  signers, discussion, approved_by?, signed_date?, signed_by?, html_path?,
  json_path?, published_url?, archived_thread_id?}`, used for
  persistent-view re-registration and the takedown command). `signers` is
  itself a dict of `role` → `{user_id, status, dm_message_id, channel_message_id}`
  (`status` ∈ `unassigned | pending | signed | declined | stale` — `stale`
  means they signed, but `FilingManager.edit_field` changed an answer since,
  so it no longer covers what they agreed to; treated identically to
  `declined` everywhere except the button label). Exactly one of
  `dm_message_id`/`channel_message_id` is set once a signer is `pending` —
  whichever the `SignerRequestView` actually got posted to (DM by default,
  the filing's review channel as a fallback if the DM was blocked — see
  "Filing lifecycle" step 2) — both restart re-registration and `deny()`'s
  "no action needed" edit check `dm_message_id` first, then
  `channel_message_id`. One entry per handoff-required signer role.
  `discussion` is a
  list of `{author_id, author_label, content, at}`, one entry per human
  message posted in the filing's private review channel. `template_access`
  (dict of `template_id` → `[role_id, ...]`; a template missing from this
  dict, or mapped to an empty list, is open to everyone — see "Filing
  access gates" above).
- **User**: `active_filing` (`{"template_id", "guild_id", "field_index",
  "answers"}`), the in-progress DM Q&A state.
- **Global**: `filing_counters` (`{"<template_id>-<year>": int}`, backing the
  `filing_id` scheme); `site_repo` (`"owner/repo"`, serves as both the
  templates source and publish destination), `site_branch` (default
  `"main"`), `site_base_url` (optional override, else computed as
  `https://{owner}.github.io/{repo}`).
