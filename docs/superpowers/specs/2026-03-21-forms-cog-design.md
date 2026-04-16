# Forms Cog — Design Specification
**Date:** 2026-03-21
**Repo:** emenblade/cogs
**Cog name:** `forms`
**RedBot version:** V3/V4 (discord.py 2.x)

---

## Overview

A RedBot cog providing two integrated systems: **Tickets** and **Applications**. Both are operated entirely through Discord-native UI (buttons, select menus, ephemeral messages, DMs). No web dashboard. Minimal command surface — just two admin commands; everything else is GUI.

Designed for reliability at scale (hundreds of concurrent users), clean UX inspired by APPY bot's philosophy of keeping users inside Discord at all times.

---

## Architecture

### Approach
Single cog package — Option A. RedBot-native storage only. No external dependencies beyond `discord.py` and `redbot.core`.

### Package layout

```
forms/
├── __init__.py          # async setup(bot); registers persistent views; declares end-user data statement
├── info.json            # cog metadata (see Deployment section for required fields)
├── forms.py             # main Cog class; registers commands, setup wizard
├── tickets.py           # ticket create / close / transcript logic
├── applications.py      # app builder, DM Q&A flow, review logic
├── views.py             # all Discord UI Views, buttons, select menus, modals
└── utils.py             # transcript builder, permission checks, shared helpers
```

### Storage

| Store | Used for |
|---|---|
| **RedBot Config API** (guild-scoped) | All settings (channel IDs, role IDs, forum IDs, categories, cooldowns), live state (open ticket count per user, in-progress application state, ticket counter) |
| **`cog_data_path/applications/`** | One JSON file per saved application template (name, description, questions list) |
| **`cog_data_path/transcripts/`** | Full ticket transcripts saved as `.txt` files (named by ticket number). Sent as file attachments when content exceeds Discord message limits. |

### Config schema (guild-scoped defaults)

```python
# Tickets
ticket_channel: None          # channel ID — where Open Ticket button lives
ticket_category: None         # category ID — where ticket channels are created
ticket_user_role: None        # role ID — required to open a ticket
ticket_staff_role: None       # role ID — can close tickets
ticket_forum: None            # forum channel ID — both ticket and application transcripts posted here
ticket_categories: []         # list of str — select menu options (e.g. "Bug Report"). Min 1 required before panel is active.
ticket_counter: 0             # int — global ever-incrementing ticket number (increments under asyncio.Lock)
ticket_panel_message: None    # message ID of the persistent ticket embed (one per guild)
ticket_max_open: 3            # int — max concurrent open tickets per user (configurable)

# Per-user ticket state (member-scoped)
open_tickets: []              # list of channel IDs currently open for this user

# Applications
application_assignments: {}   # guild-scoped dict keyed by slug
# {
#   "mod-application": {
#     "channel_id": int,
#     "panel_message_id": int,
#     "approval_role_id": int,
#     "cooldown_days": int
#   }
# }

# Per-user application state (member-scoped)
application_cooldowns: {}     # { "mod-application": unix_timestamp_of_expiry }
active_application: None      # ONE active application at a time per user (across all slugs):
                              # { "slug": str, "guild_id": int, "question_index": int, "answers": [] }
                              # guild_id is stored here so the DM listener can resolve guild Config
```

---

## Command Surface

| Command | Who | Purpose |
|---|---|---|
| `[p]forms setup` | Bot owner / admin | First-run guided wizard |
| `[p]forms settings` | Configurable staff role | Ongoing settings panel (ephemeral) |

Everything else — creating tickets, applying, approving, denying, building and managing applications — is done through Discord UI components.

`[p]forms settings` uses a dynamic permission check: a `commands.check` decorator that reads `ticket_staff_role` from Config for the invoking guild and verifies the member has that role. This avoids hardcoding a role name.

---

## Persistent Views — Bot Restart Handling

Discord.py 2.x persistent views (`timeout=None`) stop responding after a bot restart unless explicitly re-registered. On cog load (`setup()` in `__init__.py`), the bot must:

1. For each guild, read `ticket_panel_message` from Config. If set, call `bot.add_view(TicketPanelView(config), message_id=ticket_panel_message)`.
2. For each guild, iterate `open_tickets` across all members. For each open ticket channel, call `bot.add_view(CloseTicketView(config), message_id=<close_button_message_id>)`. The close-button message ID must be stored in Config alongside the ticket channel ID.
3. For each slug in `application_assignments`, iterate `active_reviews`. For each `user_id` entry, call `bot.add_view(ReviewView(config, slug, user_id), message_id=active_reviews[user_id]["review_message_id"])`.

All persistent `View` subclasses must assign stable, deterministic `custom_id` values to their buttons (e.g. `"forms:open_ticket"`, `"forms:close_ticket:{channel_id}"`, `"forms:approve:{slug}:{user_id}"`) so they survive across sessions.

---

## DM Listener — Application Answer Routing

When a user is mid-application, the bot must listen for their DM replies. This is implemented as an `on_message` listener in `applications.py`:

```python
@commands.Cog.listener()
async def on_message(self, message: discord.Message):
    if message.guild is not None:   # ignore guild messages
        return
    if message.author.bot:
        return
    # Check if this user has an active application in ANY guild
    state = await self.config.user(message.author).active_application()
    if state is None:
        return
    guild = self.bot.get_guild(state["guild_id"])
    if guild is None:
        return
    member = guild.get_member(message.author.id)
    if member is None:
        return
    await self._handle_application_reply(member, guild, state, message)
```

`guild_id` is stored inside `active_application` at the time the application starts, so the listener can always resolve the correct guild's Config without any guild context from the DM itself. Because `active_application` is stored at user-scope (not member-scope), the lookup `self.config.user(message.author)` works in a DM context.

**Concurrency:** The listener is safe for simultaneous users because each user's `active_application` is independent. Answers are written with Config's async context manager which handles its own locking.

**Note:** `application_cooldowns` and `open_tickets` remain member-scoped (require guild context) as they are only accessed from guild interactions. Only `active_application` is stored user-scoped to support the DM listener.

---

## Tickets System

### Setup (via wizard or settings panel)
Staff configures:
- Ticket channel (button lives here)
- Ticket category (channels created here, inheriting category permissions)
- User role (required to interact with Open Ticket button)
- Staff role (can click Close Ticket)
- Staff forum (transcripts archived here — shared with applications)
- Ticket categories — list of options shown in the select menu
- Max open tickets per user (default: 3)

On first run, the wizard also creates two forum tags in the staff forum: `TICKET` and `APPLICATION`. If the tags already exist, they are reused. This is done via `ForumChannel.create_tag()`. The tag IDs are stored in Config for use at transcript-post time.

### User flow

1. User visits ticket channel. Bot has posted a persistent embed with an **🎫 Open Ticket** button. Only users with the configured role can interact with it. If `ticket_categories` is empty, the button shows an ephemeral error: "Tickets are not fully configured yet. Please contact staff."

2. User clicks button. Bot checks: does this user already have `ticket_max_open` or more open tickets? If yes → ephemeral error. Otherwise → ephemeral select menu of ticket categories (Discord `ui.Select`, max 25 options — sufficient for typical category lists).

3. User selects a category. Bot acquires a per-guild `asyncio.Lock` before reading, incrementing, and writing `ticket_counter` — guaranteeing unique numbers under concurrent load. Bot creates a new text channel named `{sanitised_username}-{counter:04d}` inside the configured category. Username is sanitised: lowercased, spaces replaced with hyphens, non-alphanumeric characters stripped, truncated to 80 chars to stay within Discord's 100-char channel name limit.

4. Bot posts in the new channel:
   - @mentions the user
   - States the selected category
   - Asks the user to describe their issue in detail
   - Includes a **🔒 Close Ticket** button (`custom_id: "forms:close_ticket:{channel_id}"`, disabled for everyone except users with the staff role via interaction check)
   - The message ID of this bot post is stored in Config under the ticket entry so the view can be re-registered on restart

5. User types freely in the channel. Staff responds.

6. When resolved, staff clicks **Close Ticket**:
   - Bot collects all messages from the channel, ordered chronologically, and builds a formatted transcript
   - Transcript is written to `cog_data_path/transcripts/ticket-{counter:04d}.txt`
   - If transcript ≤ 1900 chars: DM user as plain text. If > 1900 chars: DM user the `.txt` file as an attachment
   - Bot creates a forum post in the staff forum: named the same as the ticket channel, tagged `TICKET` (using stored tag ID), body contains the transcript (same size rule: inline if ≤ 4000 chars, otherwise attached as file), thread marked closed
   - Bot deletes the ticket channel
   - Bot removes the ticket from the user's `open_tickets` in Config

### Limits & guards
- Max open tickets per user: configurable via `ticket_max_open` (default 3)
- Ticket counter is globally unique per guild, protected by `asyncio.Lock`
- Role check is enforced on button interaction, not just channel permissions
- Channel name is sanitised to comply with Discord naming rules

---

## Applications System

### Application template format (JSON file, saved in `cog_data_path/applications/`)

```json
{
  "name": "Mod Application",
  "slug": "mod-application",
  "description": "Apply to join our moderation team. We're looking for active, fair-minded members.",
  "questions": [
    "How old are you?",
    "How long have you been a member of this server?",
    "Why do you want to be a moderator?"
  ]
}
```

### Staff: building an application

1. From the settings panel, staff clicks **Manage Applications** → sees a list of existing applications and a **＋ Create New** button.

2. A short modal opens: **application name** and **user-facing description**. These are short fields — modal is appropriate.

3. Bot checks that the staff member has DMs open by attempting the first DM. If `discord.Forbidden` is raised, bot sends an ephemeral error: "Please enable DMs from server members to use the application builder."

4. Bot DMs the staff member the question builder:
   - "What is question 1? Reply `done` when you are finished adding questions."
   - Staff replies with the question text. Bot confirms ("✅ Question 1 saved.") and asks for the next.
   - Repeats up to 50 questions.
   - When staff replies `done`, bot saves the JSON file and DMs a numbered summary of all questions for review.

5. **Edit:** Staff selects an existing application from the settings panel and clicks **Edit**. Two options appear as buttons:
   - **Edit name/description** → modal with current values pre-filled
   - **Edit questions** → re-enters DM question builder. Bot presents each existing question one at a time: "Question 1 is currently: [text]. Reply with new text or `keep` to leave it unchanged." After iterating all existing questions, bot asks if they want to add more. This allows partial edits.

6. **Delete:** Staff selects application → confirmation button ("Are you sure? This cannot be undone.") → bot removes the JSON file, clears `application_assignments` entry for this slug, and the panel message in the assigned channel (if any) is deleted.

### Staff: assigning an application

From the settings panel, staff selects a saved application and:
- Picks a **channel** using a hybrid command with `app_commands.autocomplete` (not a plain `ui.Select`) to support large servers with many channels
- Picks an **approval role** using the same autocomplete mechanism
- Sets a **cooldown** in days (modal, short text field)

Bot posts a clean embed in the chosen channel: application name, description, and a **📋 Apply** button (`custom_id: "forms:apply:{slug}"`). The message ID is saved to `application_assignments[slug]["panel_message_id"]`.

Multiple applications can share a single hub channel — each gets its own embed. The channel can be a dedicated channel or a shared hub.

### User: filling out an application

1. User sees the application embed. On button click, bot checks:
   - Does the user already have an `active_application` in progress? → ephemeral error: "You already have an application in progress. Please complete it first."
   - Is the user on cooldown for this slug? → ephemeral error with time remaining (e.g. "You can re-apply in 4 days, 3 hours.")
   - Can the bot DM the user? → attempt DM; if `discord.Forbidden`, ephemeral error: "Please enable DMs from server members to apply."

2. Bot stores `active_application = { "slug": slug, "guild_id": guild.id, "question_index": 0, "answers": [] }` in user-scoped Config. Bot sends DM question 1: "Thanks for applying for **Mod Application**! Question 1 of 12: [question text]"

3. User replies in DM. Bot saves answer to `active_application.answers` immediately (bot-restart safe). Bot sends question 2. Progress shown: "Question 2 of 12: ...". Repeats until all questions answered. Only one application active at a time per user across all slugs.

4. After the final answer, bot sends: "Your application has been submitted! Staff will review it within 5 days. We'll DM you with their decision." Bot clears `active_application` from Config.

5. Bot creates a forum post in the staff forum:
   - Title: `Mod Application — {username}`
   - Tagged: `APPLICATION` (using stored tag ID)
   - Body: full Q&A transcript (inline if ≤ 4000 chars, `.txt` attachment if larger)
   - Two buttons: **✅ Approve** (`custom_id: "forms:approve:{slug}:{user_id}"`) and **❌ Deny** (`custom_id: "forms:deny:{slug}:{user_id}"`)
   - The forum post (thread) ID and the review message ID are stored in `application_assignments[slug]["active_reviews"]` dict keyed by `user_id`, so the view can be re-registered on restart.

6. **Approve:** assigns configured role → DMs user "Congratulations, your **Mod Application** has been approved!" → closes forum post thread → clears `application_cooldowns` for this slug (approved users are not put on cooldown) → removes from `active_reviews`.

7. **Deny:** opens a short modal for the denial reason (1 field, modal is fine — short text) → DMs user "Your **Mod Application** was not approved. Reason: [reason]" → closes forum post thread → sets `application_cooldowns[slug]` to `now + cooldown_days * 86400` → removes from `active_reviews`.

### Limits & guards
- Only one active application per user at a time (across all slugs). A user finishing or being denied one can then start another.
- Cooldown enforced per-user per-application-slug
- Up to 50 questions per application
- In-progress answers saved after each reply — bot restart safe
- DM-closed check before starting both builder (staff) and application (user) flows

---

## Setup & Settings

### First run — `[p]forms setup`

Guided wizard using buttons, select menus, autocomplete, and modals. Steps:

1. Select **ticket channel** (autocomplete)
2. Select **ticket category** (autocomplete)
3. Select **user role** — who can open tickets (autocomplete)
4. Select **staff role** — who can close tickets and use `[p]forms settings` (autocomplete)
5. Select **staff forum** — receives both ticket and application transcripts (autocomplete)
6. Bot creates (or verifies) `TICKET` and `APPLICATION` tags on the staff forum. Stores tag IDs in Config.
7. Add **ticket categories** — modal with up to 5 text fields at a time; repeat until done. At least one required.
8. Set **max open tickets** per user (modal, default 3)

On completion, bot auto-posts the persistent ticket embed in the ticket channel. Wizard can be re-run at any time.

### Ongoing — `[p]forms settings`

Posts an ephemeral settings panel. Accessible to members with the configured staff role.

**🎫 Ticket Settings**
- Change ticket channel / category / roles / forum (autocomplete selects)
- Add or remove ticket categories
- Change max open tickets per user
- Re-post ticket embed (if original message was deleted)

**📋 Application Settings**
- Create / edit / delete applications
- Assign application to a channel (with approval role and cooldown)
- Change approval role or cooldown for an existing assignment
- Re-post application embed (if original message was deleted)

---

## UI Component Strategy

| Input type | Method | Reason |
|---|---|---|
| Channel / role / forum selection | `app_commands.autocomplete` on hybrid commands | Handles large servers; not capped at 25 like `ui.Select` |
| Short categorical selection (ticket category, app choice) | `ui.Select` | ≤25 options; sufficient for typical configs |
| Short text (app name, denial reason, cooldown days) | Modal (1–2 fields) | Short enough, no timeout risk |
| Long text (questions, answers) | DM back-and-forth | No timeout; user can take their time |
| Decisions (approve/deny, confirm delete) | Buttons | Instant, no typing required |

---

## Error Handling

- All button interactions verify permissions before acting (role check via interaction, not channel visibility)
- Graceful ephemeral errors for: cooldown active, max tickets open, application already in progress, missing configuration, DMs closed
- Persistent views re-registered on cog load (see Persistent Views section)
- If bot restarts mid-application DM flow, state is preserved in user-scoped Config; next user reply resumes
- If a configured channel/role/forum is deleted, bot logs a warning and surfaces a clear error to the next staff member who uses the settings panel
- If the `TICKET` or `APPLICATION` forum tags are deleted, bot surfaces an error on the next close/submission and prompts staff to re-run setup to recreate them
- `ticket_categories` empty guard: Open Ticket button shows ephemeral error if no categories configured

---

## Privacy & RedBot Compliance

This cog stores user-identifiable data (application answers, DM transcripts, ticket history). Per RedBot V3/V4 requirements:

- `__init__.py` must declare `__red_end_user_data_statement__` describing what is stored
- The Cog class must implement `async def red_get_data_for_user(self, *, requester, user_id)` and `async def red_delete_data_for_user(self, *, requester, user_id)` to comply with RedBot's data deletion API
- `info.json` must include `"end_user_data_statement"` field

---

## Deployment

### `info.json` required fields

```json
{
  "name": "Forms",
  "short": "Tickets and application forms, Discord-native.",
  "description": "A fully GUI-driven tickets and applications system for RedBot.",
  "author": ["emenblade"],
  "install_msg": "Load with `[p]load forms`, then run `[p]forms setup` to configure.",
  "min_bot_version": "3.5.0",
  "min_python_version": [3, 8, 0],
  "end_user_data_statement": "This cog stores application answers, ticket transcripts, and per-user state. Data can be deleted on request via `[p]mydata forgetme`."
}
```

### Installation

```
[p]repo add emenblade-cogs https://github.com/emenblade/cogs
[p]cog install emenblade-cogs forms
[p]load forms
[p]forms setup
```

No additional pip requirements beyond `redbot[voice]`.
