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

    async def create_ticket(
        self, interaction: discord.Interaction, category_name: str
    ) -> None:
        """Create a ticket channel, post the welcome message, and update state."""
        from .views import CloseTicketView

        guild = interaction.guild
        guild_conf = self.config.guild(guild)

        # Atomic counter increment
        async with self._get_lock(guild.id):
            counter = await guild_conf.ticket_counter()
            counter += 1
            await guild_conf.ticket_counter.set(counter)

        # Create channel
        category_id = await guild_conf.ticket_category()
        category = guild.get_channel(category_id)
        safe_name = sanitize_channel_name(interaction.user.display_name)
        channel_name = f"{safe_name}-{counter:04d}"

        overwrites = dict(category.overwrites) if category else {}
        overwrites[interaction.user] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True
        )
        overwrites[guild.me] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, manage_channels=True
        )

        channel = await category.create_text_channel(
            channel_name, overwrites=overwrites
        )

        # Post welcome message with close button
        staff_role_id = await guild_conf.ticket_staff_role()
        view = CloseTicketView(self.config, self.bot, channel.id, staff_role_id)
        embed = discord.Embed(
            title=f"Ticket #{counter:04d} — {category_name}",
            description=(
                f"{interaction.user.mention}, thanks for opening a ticket!\n\n"
                f"**Category:** {category_name}\n\n"
                "Please describe your issue in as much detail as possible. "
                "Staff will be with you shortly."
            ),
            color=discord.Color.blurple(),
        )
        msg = await channel.send(
            content=interaction.user.mention, embed=embed, view=view
        )

        # Persist ticket state for this member
        ticket_entry = {
            "channel_id": channel.id,
            "message_id": msg.id,
            "counter": counter,
        }
        async with self.config.member(interaction.user).open_tickets() as tickets:
            tickets.append(ticket_entry)

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
