# Slash Commands Design

**Date:** 2026-03-22
**Status:** Approved

## Summary

Add Discord slash command support to the Forms cog's two existing admin commands (`forms setup` and `forms settings`) while preserving prefix command compatibility.

## Approach

Convert the `forms` command group from `commands.group` to `commands.hybrid_group`. RedBot's `HybridGroup` makes all subcommands registered via `.command()` automatically available as both prefix commands and slash commands.

### Changes to `forms/forms.py`

**1. Import:** Add a separate import line for `app_commands`:
```python
import discord
from discord import app_commands  # add this line
from redbot.core import Config, commands
```

**2. Group decorator:** Stack `@app_commands.guild_only()` above `@commands.guild_only()` (retain both — `@commands.guild_only()` guards prefix invocations, `@app_commands.guild_only()` guards slash invocations), and change `@commands.group` to `@commands.hybrid_group`:
```python
@app_commands.guild_only()
@commands.guild_only()
@commands.hybrid_group(name="forms")
async def forms_group(self, ctx: commands.Context) -> None:
    """Forms cog commands."""
```

**3. Permission-denied message in `forms_settings`:** Add `ephemeral=True` and remove `delete_after=10`. Ephemeral interaction responses cannot be auto-deleted by the bot (they dismiss only when the user closes them), so `delete_after` has no effect for slash command invocations. Removing it keeps behavior consistent across both invocation types:
```python
await ctx.send("You don't have permission to use this command.", ephemeral=True)
```

No other changes required. The subcommand decorators (`@forms_group.command`) do not need modification — `HybridGroup.command()` automatically promotes subcommands to hybrid. All `ctx.send()` calls in the happy path work identically for prefix and slash.

## Slash Commands Produced

| Command | Description (from docstring) | Who can use |
|---|---|---|
| `/forms setup` | Run the first-time setup wizard. | Admins |
| `/forms settings` | Open the settings panel. | Staff / Admins |

## Out of Scope

- No new commands
- No slash-only commands
- No changes to views, tickets, or applications logic
