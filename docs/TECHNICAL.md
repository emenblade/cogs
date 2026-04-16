# Forms Cog — Technical Reference

A RedBot cog providing Discord-native support tickets and application forms, driven entirely by Discord UI components (buttons, selects, modals). No message-command interaction required from end users.

---

## Architecture

```
Forms (commands.Cog)
├── TicketManager          — ticket lifecycle (create, close, transcript, forum archive)
├── ApplicationManager     — application templates (CRUD), DM Q&A flow, review posting
└── views.py               — all discord.ui.View / Modal classes
```

Config is scoped at guild and member/user level via RedBot's `Config` system (identifier `0x666F726D73`).

Application templates are stored as JSON files at `<cog_data_path>/applications/<slug>.json` rather than in Config, since they can be large and are write-once-read-many.

Transcripts are saved to `<cog_data_path>/transcripts/<channel-name>.txt` on ticket close.

---

## Commands

### `/forms setup` · `[p]forms setup`

**Permission:** `administrator` (hard-coded via `@commands.admin_or_permissions`)

Runs a 7-step interactive wizard. Each step renders an embed with a `discord.ui.View` (5-minute timeout). Steps progress by editing the same message in-place.

| Step | What it configures | Config key |
|------|-------------------|------------|
| 1 | Ticket panel channel | `ticket_channel` |
| 2 | Ticket Discord category | `ticket_category` |
| 3 | Ticket user role | `ticket_user_role` |
| 4 | Staff role | `ticket_staff_role` |
| 5 | Staff forum channel | `ticket_forum` |
| 6 | Forum tags (auto-created) | `ticket_tag_id`, `application_tag_id` |
| 7 | Category names + max open | `ticket_categories`, `ticket_max_open` |

On completion, `finish_wizard()` posts the ticket panel embed to `ticket_channel` and stores the message ID in `ticket_panel_message`.

---

### `/forms settings` · `[p]forms settings`

**Permission:** administrator OR holder of `ticket_staff_role`

Opens `SettingsPanelView` — a top-level view (180s timeout) with two sub-panel buttons: **Ticket Settings** and **Application Settings**.

#### Ticket Settings (`TicketSettingsView`, 180s)

| Button | Behaviour |
|--------|-----------|
| Change Ticket Channel | Spawns `WizardStep1View` inline (5 min timeout) |
| Edit Categories | Opens `EditTicketCategoriesModal` — one textarea, newline-separated |
| Set Max Tickets | Opens `MaxTicketsModal` — accepts 1–20 |
| Re-post Ticket Panel | Calls `TicketManager.post_panel()`, updates `ticket_panel_message` |

#### Application Settings (`ApplicationSettingsView`, 180s)

| Button | Behaviour |
|--------|-----------|
| Create Application | Opens `CreateApplicationModal` → DM question builder (10 min/question, max 50) |
| Edit Application | Select dropdown → DM edit flow (5 min/question) |
| Delete Application | Select dropdown → `ConfirmView` → deletes JSON + clears config assignment |
| Assign to Channel | 3-step ephemeral flow: select app → select channel → select role → cooldown modal |

---

## Ticket Flow

```
User clicks "Open Ticket"
  └─ TicketPanelView.open_ticket()
       ├─ Role gate (ticket_user_role)
       ├─ Max open gate (ticket_max_open)
       └─ Shows TicketCategoryView (ephemeral, 2 min timeout)
            └─ User selects category
                 └─ TicketManager.create_ticket()
                      ├─ Atomic counter increment (asyncio.Lock per guild)
                      ├─ Creates text channel under ticket_category
                      ├─ Sets overwrites: user + bot read/write, category inherited
                      ├─ Posts CloseTicketView embed in channel (persistent, no timeout)
                      └─ Appends to config.member.open_tickets

Staff clicks "Close Ticket"
  └─ CloseTicketView.close_ticket()
       ├─ Staff role gate
       ├─ TicketManager.close_ticket()
       │    ├─ Collects full channel history (oldest first)
       │    ├─ Writes transcript to disk
       │    ├─ DMs transcript to opener (silently skips if Forbidden)
       │    ├─ Posts thread to ticket_forum with TICKET tag, then archives+locks it
       │    ├─ Removes ticket from config.member.open_tickets
       │    └─ Deletes the channel
```

---

## Application Flow

```
Staff creates application
  └─ ApplicationSettingsView → CreateApplicationModal
       ├─ Name + description saved
       └─ ApplicationManager.create_application()
            └─ DM loop: bot sends prompts, staff replies (10 min timeout each)
                 └─ Saved to applications/<slug>.json

Staff assigns application to channel
  └─ ApplicationSettingsView → Assign to Channel (3-step ephemeral)
       └─ ApplicationManager.assign_application()
            ├─ Posts ApplyView embed to channel (persistent, no timeout)
            └─ Stores assignment in config.guild.application_assignments[slug]

User clicks "Apply"
  └─ ApplyView.apply()
       ├─ Guard: active_application already set?
       ├─ Guard: on cooldown?
       ├─ Guard: DMs open? (sends test message)
       └─ ApplicationManager.start_application()
            └─ Sets config.user.active_application state, sends Q1 via DM

User replies in DMs
  └─ Forms.on_message() → ApplicationManager._handle_application_reply()
       ├─ Saves answer, increments question_index
       ├─ If more questions: send next question
       └─ If all answered:
            ├─ Clears active_application
            ├─ Confirms submission to user
            └─ ApplicationManager._post_review_forum()
                 ├─ Posts Q&A transcript to ticket_forum with APPLICATION tag
                 ├─ Attaches ReviewView (persistent: Approve / Deny buttons)
                 └─ Stores review metadata in application_assignments[slug].active_reviews

Staff clicks Approve
  └─ ReviewView.approve()
       ├─ Adds approval_role_id to member
       ├─ DMs user congratulations
       ├─ Clears cooldown
       ├─ Removes from active_reviews
       └─ Archives + locks forum thread

Staff clicks Deny
  └─ ReviewView.deny() → DenyReasonModal
       ├─ DMs user denial reason
       ├─ Sets cooldown expiry (unix timestamp in config.user.application_cooldowns)
       ├─ Removes from active_reviews
       └─ Archives + locks forum thread
```

---

## Persistent Views

All views that must survive bot restarts are registered with no `timeout` and re-registered in `Forms._register_persistent_views()` on cog load. These are:

| View | custom_id pattern | Registered from |
|------|-------------------|-----------------|
| `TicketPanelView` | `forms:open_ticket` | `ticket_panel_message` per guild |
| `CloseTicketView` | `forms:close_ticket:<channel_id>` | `open_tickets` per member |
| `ApplyView` | `forms:apply:<slug>` | `application_assignments[slug].panel_message_id` |
| `ReviewView` | `forms:approve:<slug>:<user_id>` / `forms:deny:…` | `application_assignments[slug].active_reviews[user_id].review_message_id` |

---

## Config Schema

### Guild scope

| Key | Type | Description |
|-----|------|-------------|
| `ticket_channel` | `int \| None` | Channel ID for ticket panel |
| `ticket_category` | `int \| None` | Category ID for new ticket channels |
| `ticket_user_role` | `int \| None` | Role required to open tickets |
| `ticket_staff_role` | `int \| None` | Role that can close tickets / access settings |
| `ticket_forum` | `int \| None` | Forum channel for transcripts and reviews |
| `ticket_categories` | `list[str]` | Category names shown in the category select |
| `ticket_counter` | `int` | Monotonically increasing ticket number |
| `ticket_panel_message` | `int \| None` | Message ID of the posted ticket panel |
| `ticket_max_open` | `int` | Max concurrent open tickets per user (default 3) |
| `ticket_tag_id` | `int \| None` | Forum tag ID for TICKET threads |
| `application_tag_id` | `int \| None` | Forum tag ID for APPLICATION threads |
| `application_assignments` | `dict[slug, AssignmentDict]` | Per-slug assignment data |

**AssignmentDict:**
```python
{
    "channel_id": int,
    "panel_message_id": int,
    "approval_role_id": int | None,
    "cooldown_days": int,
    "active_reviews": {
        "<user_id>": {
            "thread_id": int,
            "review_message_id": int
        }
    }
}
```

### Member scope (per guild)

| Key | Type | Description |
|-----|------|-------------|
| `open_tickets` | `list[TicketEntry]` | List of `{channel_id, message_id, counter}` |

### User scope (global)

| Key | Type | Description |
|-----|------|-------------|
| `active_application` | `dict \| None` | Current in-progress application state |
| `application_cooldowns` | `dict[slug, float]` | Unix timestamp of cooldown expiry per slug |

---

## Timeout Reference

| Context | Timeout | Behaviour on expiry |
|---------|---------|---------------------|
| Setup wizard steps 1–7 | 300s | Buttons disabled; re-run `setup` |
| `TicketCategoryView` | 120s | Select disappears; user clicks Open Ticket again |
| `TicketSettingsView` | 180s | Buttons disabled; re-run `settings` |
| `ApplicationSettingsView` | 180s | Buttons disabled; re-run `settings` |
| `_SingleSelectView` (app select) | 60s | Select disappears; re-open settings |
| `ConfirmView` | 60s | Buttons disabled; re-open settings |
| `_ChannelSelectStepView` | 120s | Select disappears; re-open settings |
| `_RoleSelectStepView` | 120s | Select disappears; re-open settings |
| `_OpenModalView` (cooldown) | 120s | Button disappears; re-open settings |
| Application builder DM (new questions) | 600s/question | Partial progress saved; re-run create |
| Application builder DM (edit) | 300s/question | Remaining questions kept as-is |
| Application builder DM (add more?) | 120s | No extra questions added |

Persistent views (`TicketPanelView`, `CloseTicketView`, `ApplyView`, `ReviewView`) have `timeout=None` and never expire.

---

## Privacy / GDPR

RedBot's data API is implemented:

- `red_get_data_for_user(user_id)` — returns `config.user` data.
- `red_delete_data_for_user(user_id)` — clears `config.user` and `config.member` across all guilds.

Application JSON files on disk are **not** automatically purged by these calls (they contain no PII beyond what staff typed into the questions themselves).

---

## Known Limitations

- The `on_message` DM listener routes all DMs to the active application; a user can only have one in-progress application at a time.
- Application builder questions entered via DM are not validated for length beyond Discord's 2000-character message limit.
- `ticket_counter` is per-guild and monotonically increasing; there is no reset mechanism.
- Forum tag creation during setup will silently use existing tags if `TICKET`/`APPLICATION` names already exist.
