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

    async def post_panel(self, channel: discord.TextChannel) -> discord.Message:
        """Post (or re-post) the persistent ticket panel embed in the given channel."""
        from .views import TicketPanelView
        embed = discord.Embed(
            title="🎫 Support Tickets",
            description="Click the button below to open a support ticket. "
                        "Please only open a ticket if you need assistance.",
            color=discord.Color.blurple(),
        )
        view = TicketPanelView(self.config, self.bot)
        msg = await channel.send(embed=embed, view=view)
        await self.config.guild(channel.guild).ticket_panel_message.set(msg.id)
        return msg
