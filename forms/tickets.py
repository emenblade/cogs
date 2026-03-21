"""Ticket creation, closing, and transcript logic."""
from __future__ import annotations
import asyncio
import discord
from redbot.core import Config
from redbot.core.bot import Red
from .utils import sanitize_channel_name, build_transcript, send_or_attach


class TicketManager:
    def __init__(self, bot: Red, config: Config) -> None:
        self.bot = bot
        self.config = config
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]
