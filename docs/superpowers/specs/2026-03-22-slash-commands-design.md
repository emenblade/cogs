# Slash Commands Design

**Date:** 2026-03-22
**Status:** Approved

## Summary

Add Discord slash command support to the Forms cog's two existing admin commands (`forms setup` and `forms settings`) while preserving prefix command compatibility.

## Approach

Convert the `forms` command group from `commands.group` to `commands.hybrid_group`. RedBot's hybrid group makes all subcommands automatically available as both prefix commands and slash commands.

**Change:** `forms/forms.py` line 127
```python
# Before
@commands.group(name="forms")

# After
@commands.hybrid_group(name="forms")
```

No other changes required. Subcommands (`setup`, `settings`) inherit hybrid behavior. Existing `ctx.send()` calls work identically for both interaction types. Existing permission checks (`@commands.admin_or_permissions`, guild_only, staff role check) remain unchanged.

## Slash Commands Produced

| Command | Description (from docstring) | Who can use |
|---|---|---|
| `/forms setup` | Run the first-time setup wizard. | Admins |
| `/forms settings` | Open the settings panel. | Staff / Admins |

## Out of Scope

- No new commands
- No slash-only commands
- No changes to views, tickets, or applications logic
