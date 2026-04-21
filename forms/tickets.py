"""Ticket creation, closing, and transcript logic."""
from __future__ import annotations
import asyncio
import io
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

        # Re-check open ticket limit (guard against race between panel check and here)
        max_open = await guild_conf.ticket_max_open()
        open_tickets_now = await self.config.member(interaction.user).open_tickets()
        if len(open_tickets_now) >= max_open:
            try:
                await interaction.followup.send(
                    f"⚠️ You already have {len(open_tickets_now)} open ticket(s). "
                    "Please wait for them to be resolved before opening a new one.",
                    ephemeral=True,
                )
            except Exception:
                pass
            return

        # Atomic counter increment
        async with self._get_lock(guild.id):
            counter = await guild_conf.ticket_counter()
            counter += 1
            await guild_conf.ticket_counter.set(counter)

        # Create channel
        category_id = await guild_conf.ticket_category()
        category = guild.get_channel(category_id)
        if category is None:
            try:
                await interaction.followup.send(
                    "⚠️ Ticket category not found. Please ask staff to re-run setup.",
                    ephemeral=True,
                )
            except Exception:
                pass
            return
        safe_category = sanitize_channel_name(category_name, max_length=40, fallback="ticket")
        safe_user = sanitize_channel_name(interaction.user.display_name, max_length=20)
        channel_name = f"{safe_category}-{safe_user}-{counter:04d}"

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
            "category": category_name,
        }
        async with self.config.member(interaction.user).open_tickets() as tickets:
            tickets.append(ticket_entry)

    async def close_ticket(
        self, channel: discord.TextChannel, guild: discord.Guild
    ) -> None:
        """Close a ticket: transcript → DM user → forum post → delete channel."""
        from redbot.core.data_manager import cog_data_path

        guild_conf = self.config.guild(guild)

        # Collect messages oldest-first
        messages = [m async for m in channel.history(limit=None, oldest_first=True)]
        transcript_text = build_transcript(messages)

        # Save transcript to disk
        transcript_dir = cog_data_path(self.bot.cogs["Forms"]) / "transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        transcript_file = transcript_dir / f"{channel.name}.txt"
        transcript_file.write_text(transcript_text, encoding="utf-8")

        # Find the ticket opener and metadata from config
        opener = None
        opener_id = None
        ticket_msg_id = None
        ticket_category = None
        found_ticket = False
        all_member_data = await self.config.all_members(guild)
        for member_id_str, data in all_member_data.items():
            for ticket in data.get("open_tickets", []):
                if ticket.get("channel_id") == channel.id:
                    opener_id = int(member_id_str)
                    opener = guild.get_member(opener_id)
                    ticket_msg_id = ticket.get("message_id")
                    ticket_category = ticket.get("category")
                    found_ticket = True
                    break
            if found_ticket:
                break

        # Remove action buttons from the welcome message before archiving
        if ticket_msg_id:
            try:
                welcome_msg = await channel.fetch_message(ticket_msg_id)
                await welcome_msg.edit(view=None)
            except Exception:
                pass

        # DM transcript to opener
        if opener:
            try:
                await send_or_attach(
                    opener,
                    f"**Transcript for {channel.name}:**\n\n{transcript_text}",
                    filename=f"{channel.name}.txt",
                )
            except discord.Forbidden:
                pass  # User has DMs closed

        # Post to staff forum
        forum_id = await guild_conf.ticket_forum()
        forum = guild.get_channel(forum_id) if forum_id else None
        if forum and isinstance(forum, discord.ForumChannel):
            # Find or create a forum tag matching the ticket category
            tags = []
            if ticket_category:
                existing_tags = {t.name.lower(): t for t in forum.available_tags}
                tag = existing_tags.get(ticket_category.lower())
                if tag is None:
                    try:
                        tag = await forum.create_tag(name=ticket_category[:20])
                    except Exception:
                        tag = None
                if tag:
                    tags = [tag]

            body = transcript_text[:2000] if transcript_text else "(empty)"
            thread, _first_msg = await forum.create_thread(
                name=channel.name,
                content=body,
                applied_tags=tags,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            if len(transcript_text) > 2000:
                fp = io.BytesIO(transcript_text.encode("utf-8"))
                await thread.send(
                    content="Full transcript attached:",
                    file=discord.File(fp, filename=f"{channel.name}.txt"),
                )
            await thread.edit(archived=True, locked=True)

        # Remove from opener's open_tickets (handles member having left the guild)
        if opener_id:
            if opener:
                async with self.config.member(opener).open_tickets() as tickets:
                    tickets[:] = [t for t in tickets if t.get("channel_id") != channel.id]
            else:
                async with self.config.member_from_ids(guild.id, opener_id).open_tickets() as tickets:
                    tickets[:] = [t for t in tickets if t.get("channel_id") != channel.id]

        # Delete the channel
        await channel.delete(reason="Ticket closed")

    async def post_panel(self, channel: discord.TextChannel) -> discord.Message:
        """Post (or re-post) the persistent ticket panel embed in the given channel."""
        from .views import TicketPanelView
        guild_conf = self.config.guild(channel.guild)

        # Delete the previous panel if it exists in this channel
        old_msg_id = await guild_conf.ticket_panel_message()
        if old_msg_id:
            try:
                old_msg = await channel.fetch_message(old_msg_id)
                await old_msg.delete()
            except Exception:
                pass

        embed = discord.Embed(
            title="🎫 Support Tickets",
            description="Click the button below to open a support ticket. "
                        "Please only open a ticket if you need assistance.",
            color=discord.Color.blurple(),
        )
        view = TicketPanelView(self.config, self.bot)
        msg = await channel.send(embed=embed, view=view)
        await guild_conf.ticket_panel_message.set(msg.id)
        return msg
