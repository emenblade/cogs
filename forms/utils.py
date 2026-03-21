"""Shared utility functions for the Forms cog."""
from __future__ import annotations
import io
import re
import discord


def sanitize_channel_name(name: str) -> str:
    """Return a Discord-safe channel name (lowercase, hyphens, max 80 chars)."""
    name = name.lower()
    name = name.replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    name = name[:80]
    return name or "user"


def build_transcript(messages: list[discord.Message]) -> str:
    """Build a plain-text transcript from a list of messages, oldest first."""
    lines = []
    for msg in messages:
        if msg.author.bot:
            continue
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")
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
