"""Shared utility functions for the Forms cog."""
from __future__ import annotations
import re
import discord


def sanitize_channel_name(name: str) -> str:
    """Return a Discord-safe channel name (lowercase, hyphens, max 80 chars)."""
    raise NotImplementedError


def build_transcript(messages: list[discord.Message]) -> str:
    """Build a plain-text transcript from a list of messages, oldest first."""
    raise NotImplementedError


async def send_or_attach(
    destination: discord.abc.Messageable,
    content: str,
    filename: str = "transcript.txt",
    threshold: int = 1900,
) -> None:
    """Send content as text if short enough, otherwise as a .txt file attachment."""
    raise NotImplementedError


def check_staff_role(interaction: discord.Interaction, role_id: int | None) -> bool:
    """Return True if the interaction member has the given role ID."""
    raise NotImplementedError
