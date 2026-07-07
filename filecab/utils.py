"""Shared utility functions for the Filecab cog."""
from __future__ import annotations
import re
import discord

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_template(html: str, answers: dict[str, str]) -> str:
    """Substitute `{{field_key}}` placeholders in an HTML template.

    Unmatched placeholders are left as-is rather than raising, so a template
    referencing a field that wasn't collected doesn't break rendering.
    """
    def _sub(match: re.Match) -> str:
        return answers.get(match.group(1), match.group(0))

    return _PLACEHOLDER_RE.sub(_sub, html)


def slugify(text: str, max_length: int = 60, fallback: str = "document") -> str:
    """Return a filesystem/URL-safe slug (lowercase, hyphens, truncated)."""
    text = text.lower().replace(" ", "-")
    text = re.sub(r"[^a-z0-9\-]", "", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-")[:max_length]
    return text or fallback


def check_staff_role(interaction: discord.Interaction, role_id: int | None) -> bool:
    """Return True if the interaction member has the given role ID."""
    if role_id is None:
        return False
    roles = getattr(interaction.user, "roles", None)
    if not roles:
        return False
    return any(r.id == role_id for r in roles)


async def can_review(interaction: discord.Interaction, approval_role_id: int | None) -> bool:
    """Return True if the interacting user can approve/deny filings."""
    if interaction.user.guild_permissions.administrator:
        return True
    return check_staff_role(interaction, approval_role_id)
