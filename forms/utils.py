"""Shared utility functions for the Forms cog."""
from __future__ import annotations
import io
import re
import discord

_MIN_RULE_RE = re.compile(r'\s*\[min:(\d+)(w?)\]\s*$', re.IGNORECASE)


def parse_question(text: str) -> tuple[str, dict | None]:
    """Strip an optional [min:N] or [min:Nw] rule tag from the end of a question.

    Returns (display_text, rule) where rule is None or
    {"type": "chars" | "words", "min": int}.
    """
    m = _MIN_RULE_RE.search(text)
    if not m:
        return text.strip(), None
    rule_type = "words" if m.group(2).lower() == "w" else "chars"
    display = text[:m.start()].strip()
    return display, {"type": rule_type, "min": int(m.group(1))}


def sanitize_channel_name(name: str, max_length: int = 80, fallback: str = "user") -> str:
    """Return a Discord-safe channel name segment (lowercase, hyphens, truncated)."""
    name = name.lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")[:max_length]
    return name or fallback


def build_transcript(messages: list[discord.Message]) -> str:
    """Build a plain-text transcript from a list of messages, oldest first."""
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


async def send_or_attach(
    destination: discord.abc.Messageable,
    content: str,
    filename: str = "transcript.txt",
    threshold: int = 1900,
) -> None:
    """Send content as text if short enough, otherwise as a .txt file attachment."""
    if len(content) <= threshold:
        await destination.send(content)
    else:
        fp = io.BytesIO(content.encode("utf-8"))
        await destination.send(file=discord.File(fp, filename=filename))


def check_staff_role(interaction: discord.Interaction, role_id: int | None) -> bool:
    """Return True if the interaction member has the given role ID."""
    if role_id is None:
        return False
    roles = getattr(interaction.user, "roles", None)
    if not roles:
        return False
    return any(r.id == role_id for r in roles)
