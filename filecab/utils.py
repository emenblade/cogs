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
    the gate; staff without Administrator still need to use `filecab file`
    (which bypasses gates entirely) rather than the public panel.
    """
    if interaction.user.guild_permissions.administrator:
        return True
    return any(check_staff_role(interaction, role_id) for role_id in allowed_role_ids)


def build_channel_transcript(messages: list[discord.Message]) -> str:
    """Build a plain-text transcript of a channel's full message history, oldest first."""
    lines = []
    for msg in messages:
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M UTC")
        author = f"[BOT] {msg.author.display_name}" if msg.author.bot else msg.author.display_name
        content = msg.content
        if not content and msg.embeds:
            titles = [e.title for e in msg.embeds if e.title]
            content = f"[embed: {', '.join(titles)}]" if titles else "[embed]"
        if content:
            lines.append(f"[{ts}] {author}: {content}")
        for att in msg.attachments:
            lines.append(f"  [Attachment: {att.filename} — {att.url}]")
    return "\n".join(lines)


async def get_or_create_forum_tag(forum: discord.ForumChannel, name: str) -> discord.ForumTag | None:
    """Return a forum tag by name, creating it if it doesn't exist yet."""
    try:
        existing = {t.name: t for t in forum.available_tags}
        if name in existing:
            return existing[name]
        return await forum.create_tag(name=name)
    except discord.HTTPException:
        return None
