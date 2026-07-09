"""Shared utility functions for the Filecab cog."""
from __future__ import annotations
import html as html_lib
import re
import discord

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_template(html_text: str, answers: dict[str, str]) -> str:
    """Substitute `{{field_key}}` placeholders in an HTML template.

    Every answer is HTML-escaped before insertion — these documents get
    published to a public site, and answers come from Discord users (DM
    replies, signer/judge modal input), so treat all of it as untrusted.
    Without escaping, a filer typing `<script>...` into any text field would
    get it embedded verbatim in the rendered page (stored XSS on the live
    site). Unmatched placeholders are left as-is rather than raising, so a
    template referencing a field that wasn't collected doesn't break
    rendering.
    """
    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in answers:
            return match.group(0)
        return html_lib.escape(answers[key])

    return _PLACEHOLDER_RE.sub(_sub, html_text)


def normalize_base_url(url: str) -> str:
    """Ensure a base URL has an http(s) scheme, so Discord renders it as a clickable link.

    A bare domain like "lcrpfilecab.emen.win" isn't auto-linked by Discord —
    only strings starting with a recognized scheme are.
    """
    url = url.strip().rstrip("/")
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url}"
    return url


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


async def can_file_template(interaction: discord.Interaction, allowed_role_ids: list[int]) -> bool:
    """Return True if the interacting user may file a gate-restricted template.

    An empty `allowed_role_ids` means the template isn't gated at all —
    callers should skip calling this and just allow it. Admins always bypass
    the gate.
    """
    if interaction.user.guild_permissions.administrator:
        return True
    roles = getattr(interaction.user, "roles", None)
    if not roles:
        return False
    allowed = set(allowed_role_ids)
    return any(r.id in allowed for r in roles)
