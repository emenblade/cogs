# Application Flow Improvements — Design Spec
_Date: 2026-04-17_

## Overview

Four targeted changes to the application system in the Forms cog:

1. Block users from applying while their application is pending review
2. Remove the cooldown step from the "Assign to Channel" wizard
3. Add a cooldown field to the denial modal
4. Replace Approve/Deny buttons with post-decision buttons after a decision is made

---

## 1. Block Pending Applications

**Location:** `ApplyView.apply()` in `forms/views.py`

After the existing "already in progress" check (checks `active_application`), add a second guard that checks `active_reviews` in guild config:

```
assignments = await self.config.guild(interaction.guild).application_assignments()
app_conf = assignments.get(self.slug, {})
if str(interaction.user.id) in app_conf.get("active_reviews", {}):
    # respond ephemeral: "Your application is currently awaiting staff review..."
    return
```

**User-facing message:** "Your application is currently awaiting staff review. Please be patient — this process can take a few days."

**Check order (final):**
1. Active application in progress → "complete it first"
2. Pending review → "awaiting staff review, be patient"
3. On cooldown → "you can re-apply in Xd Yh"
4. DMs closed → "please enable DMs"

---

## 2. Remove Cooldown from Assign Wizard

**Location:** `ApplicationSettingsView.assign_app()` in `forms/views.py`, and `assign_application()` in `forms/applications.py`

**Remove:**
- `_CooldownModal` class (only used in assign flow)
- `_OpenModalView` class (only used in assign flow)
- The cooldown step in `assign_app()` (the followup send + `await cooldown_modal.wait()`)

**Update call site** in `assign_app()` to omit `cooldown_days`.

**Update `assign_application()` signature** — remove `cooldown_days` parameter and stop storing it in the assignment dict.

The assign wizard becomes 3 steps: pick application → pick channel → pick approval role.

---

## 3. Cooldown Field on Denial Modal

**Location:** `DenyReasonModal` in `forms/views.py`

**Add a second `TextInput`:**
```
label: "Re-application cooldown (days, 0 = no cooldown)"
placeholder: "7"
max_length: 3
required: False
```

**Update `__init__`** to also accept `review_message_id: int`.

**Update `on_submit`:**
- Parse cooldown days from the new field (default 7 if blank/invalid)
- If `cooldown_days > 0`, set expiry as before; if 0, skip setting cooldown
- Post denial message in thread (unchanged)
- **Do not archive the thread** — instead, fetch the original review message by `review_message_id` and edit it to use `PostReviewView`
- Respond ephemeral to staff confirming denial

**Update `ReviewView.deny()`** to pass `review_message_id=interaction.message.id` when constructing `DenyReasonModal`.

---

## 4. Post-Decision View

**New class: `PostReviewView`** in `forms/views.py`, placed after `ReviewView`.

Persistent view (`timeout=None`) with unique custom_ids per slug+user_id (same pattern as `ReviewView`).

### Buttons

**🔄 Reset Cooldown** (`forms:reset_cooldown:{slug}:{user_id}`)
- Clears `application_cooldowns[slug]` for the target user
- Posts a note in the thread: "🔄 Cooldown cleared by @staff — @user can re-apply immediately."
- Responds ephemeral to staff: "✅ Cooldown cleared."
- No modal, single click

**📁 Close Log** (`forms:close_log:{slug}:{user_id}`)
- Archives and locks the thread
- Defers the interaction before editing

### Approve path changes (`ReviewView.approve()`)
After posting the "✅ Approved by @staff" message:
- **Do not archive** the thread
- Edit `interaction.message` to use `PostReviewView`
- Respond ephemeral: "✅ Application approved. User notified."

### Deny path changes
Handled via `DenyReasonModal.on_submit()` as described in section 3.

---

## Files Changed

| File | Changes |
|------|---------|
| `forms/views.py` | Add pending check in `ApplyView`; update `DenyReasonModal`; update `ReviewView`; add `PostReviewView`; remove `_CooldownModal`, `_OpenModalView`; update `assign_app()` |
| `forms/applications.py` | Remove `cooldown_days` from `assign_application()` |

---

## Out of Scope

- Restart recovery for `PostReviewView` (buttons will not re-register after bot restart; acceptable limitation for now)
- Any changes to the ticket system
