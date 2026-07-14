# cogs — emenblade's Red-DiscordBot Cogs

## Forms

Discord-native support tickets and application forms, driven entirely by buttons, dropdowns, and modals. No commands required from end users.

**Features:**
- 7-step setup wizard
- Private ticket channels with category selection, staff-only close, and full transcripts
- Application builder — create multi-question forms via DM, post Apply buttons to any channel
- Staff review forum with Approve/Deny buttons, automatic role assignment, and re-application cooldowns
- Persistent views survive bot restarts
- Slash command support (`/forms setup`, `/forms settings`)

### Install

```
[p]repo add cogs https://github.com/emenblade/cogs
[p]cog install cogs forms
[p]load forms
[p]forms setup
```

### Commands

| Command | Who | Description |
|---|---|---|
| `/forms setup` | Admins | Run the first-time 7-step setup wizard |
| `/forms settings` | Staff / Admins | Open the settings panel to manage tickets and applications |

### Documentation

- **[User Guide](https://blog.emen.win/Forms-cog-user-guide.html)** — step-by-step walkthrough for server members, including troubleshooting
- **[Technical Reference](docs/TECHNICAL.md)** — architecture, config schema, flow diagrams, timeout reference

---

## Filecab

Discord-native DOJ document filing. Members pick a document type from a dropdown, answer questions one at a time over DM, and the finished document goes to a private staff review channel for Approve/Deny (with optional multi-signer handoff) before an explicit "Make Public" step publishes it to a GitHub Pages site.

**Features:**
- 4-step setup wizard (document channel, review category, approval role, site repository)
- Templates are fetched from a configured GitHub repo, not bundled with the cog — add a template pair to the repo and `filecab refresh`, no code changes needed
- Each filing gets its own private channel under the review category (same mechanism as the `forms` cog's ticket channels), and the filer is added to it directly — staff can ask follow-up questions like a support ticket, with no visibility into any other filing's channel. The conversation is saved even if the channel is later deleted
- Multi-signer handoff: a filing's other roles (witness, counsel, second party, ...) get signed right in the review channel via a "Sign as X" button and a modal, same pattern as approval — no DMs involved, so nobody's Discord DM privacy settings can block it; staff use Add Person to bring in anyone who isn't already the filer or staff
- Templates can mark fields conditional (`depends_on`/`skip_value`) so redundant follow-up questions get skipped automatically and auto-filled instead of asked
- Anyone with access to a filing's channel — the filer included — can fix a wrong answer via Edit Field; if it had already been signed off on, editing warns first and marks the signature stale until the signer re-signs
- Staff can add an extra person to a filing's channel on the fly, and per-template filing access gates restrict which roles can file a given document type in the first place; staff always bypass both via `filecab file`
- Optional log forum: whether a filing is published or denied, its channel's full history gets archived to a forum post (document link — also DMed straight to the filer — or a denial note, then the transcript as a `.txt` file if it's too long for one message), tagged by category, locked, and the now-redundant channel is deleted — same mechanism as the `forms` cog's ticket-closing flow
- Settings panel: change core config, reload/refresh templates, repost the panel, manage per-template access gates, and take down or permanently delete previously filed documents
- Persistent views survive bot restarts, including a graceful fallback if a filing's template is deleted out from under it
- Bot-owner-only `filecab nuke` resets a test server to a clean slate — password-confirmed, wipes every filing record, published document, review channel, and log forum thread, while leaving templates and every other setting untouched
- Slash command support (`/filecab setup`, `/filecab settings`, `/filecab file`)

### Install

```
[p]repo add cogs https://github.com/emenblade/cogs
[p]cog install cogs filecab
[p]load filecab
[p]filecab setup
```

### Commands

| Command | Who | Description |
|---|---|---|
| `/filecab setup` | Admins | Run the first-time 4-step setup wizard |
| `/filecab settings` | Staff / Admins | Open the settings panel — config, templates, access gates, document takedown/delete |
| `/filecab file` | Staff / Admins | File any document type yourself, including judge-authored ones with no citizen role |
| `/filecab templates` | Everyone | List currently loaded templates (local only, no network call) |
| `/filecab refresh` | Staff / Admins | Fetch the latest templates from the configured site repo |
| `/filecab nuke` | Bot Owner | Password-confirmed wipe of all filing test data (records, published documents, review channels, log forum) — templates and settings are kept |

### Documentation

- **[Technical Reference](filecab/docs/TECHNICAL.md)** — architecture, UI conventions, filing lifecycle, persistence/restart safety, config schema
- **[Site Repo Contract](filecab/docs/SITE_REPO_CONTRACT.md)** — the template/publish schema a site repo's `templates/` and `filings/` folders must follow

---

## button321

A self-destruct button that DMs you 6 hours after pressing it. Do not press the button.

**Features:**
- Posts a red "self destruct do not press" button in a channel of your choice
- Ephemeral "you weren't supposed to press the button" on press
- Logs every press to a configurable log channel
- DMs the user 6 hours later: "The self-destruct sequence has been initiated."
- Persistent view survives bot restarts
- Owner-only setup, all commands gated via `@commands.is_owner()`

### Install

```
[p]repo add cogs https://github.com/emenblade/cogs
[p]cog install cogs button321
[p]load button321
[p]321button setup
```

### Commands

| Command | Who | Description |
|---|---|---|
| `/321button setup` | Bot Owner | 2-step wizard: pick button channel, pick log channel, posts the button |
| `/321button repost` | Bot Owner | Re-post the button if the message was deleted |
| `/321button status` | Bot Owner | Show config and pending notifications |

---

## gsm-autosync

Watches Docker for game server containers starting/stopping and automatically syncs them to DiscordGSM's database. Status cards appear in Discord without manual setup.

### Prerequisites

1. Mount Docker socket in your Red bot container (add to Extra Parameters in Unraid):
   `-v /var/run/docker.sock:/var/run/docker.sock`
2. Mount DiscordGSM appdata into the Red bot container:
   `/mnt/user/appdata/discordgsm` → `/discordgsm` (mode: rw)

### Install

```
[p]repo add cogs https://github.com/emenblade/cogs
[p]cog install cogs gsm-autosync
[p]load gsm-autosync
```

### Setup

```
[p]gsmsetup channel #your-channel
[p]gsmsetup scan
[p]gsmsetup status
```

### Commands

| Command | Description |
|---|---|
| `[p]gsmsetup channel #channel` | Set the Discord channel for GSM cards |
| `[p]gsmsetup dbpath /path/to/db` | Override default DB path (/discordgsm/servers.db) |
| `[p]gsmsetup addgame <name> <game_id> <port>` | Manually map a container |
| `[p]gsmsetup removegame <name>` | Remove a custom mapping |
| `[p]gsmsetup scan` | Interactive container selection |
| `[p]gsmsetup list` | Show current config |
| `[p]gsmsetup status` | Health check |
