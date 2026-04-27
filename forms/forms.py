"""Main Forms cog class."""
from __future__ import annotations
import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from .tickets import TicketManager
from .applications import ApplicationManager
from .views import WizardStep1View


class Forms(commands.Cog):
    """Discord-native tickets and application forms."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x666F726D73, force_registration=True)
        self.tickets = TicketManager(bot, self.config)
        self.applications: ApplicationManager | None = None  # set in initialize()

    async def initialize(self) -> None:
        """Register config defaults and initialize sub-managers."""
        self.config.register_guild(
            ticket_channel=None,
            ticket_category=None,
            ticket_user_role=None,
            ticket_staff_role=None,
            ticket_forum=None,
            ticket_categories=[],
            ticket_counter=0,
            ticket_panel_message=None,
            ticket_max_open=3,
            ticket_tag_id=None,
            application_tag_id=None,
            application_assignments={},
            ticket_move_categories=[],  # list of {"name": str, "category_id": int}
        )
        self.config.register_member(
            open_tickets=[],  # list of {"channel_id": int, "message_id": int, "counter": int}
        )
        self.config.register_user(
            active_application=None,
            # {"slug": str, "guild_id": int, "question_index": int, "answers": []}
            application_cooldowns={},
            # {"slug": unix_timestamp_expiry}
        )
        self.applications = ApplicationManager(
            self.bot, self.config, cog_data_path(self)
        )
        self.applications.initialize()
        await self._register_persistent_views()

    async def _register_persistent_views(self) -> None:
        """Re-register all persistent views after bot restart."""
        from .views import TicketPanelView, CloseTicketView, ApplyView, ReviewView

        all_guild_data = await self.config.all_guilds()

        for guild_id_str, guild_data in all_guild_data.items():
            guild_id = int(guild_id_str)

            # Ticket panel
            panel_msg_id = guild_data.get("ticket_panel_message")
            if panel_msg_id:
                self.bot.add_view(
                    TicketPanelView(self.config, self.bot),
                    message_id=panel_msg_id,
                )

            # Application panels
            assignments = guild_data.get("application_assignments", {})
            for slug, assignment in assignments.items():
                panel_msg_id = assignment.get("panel_message_id")
                if panel_msg_id:
                    self.bot.add_view(
                        ApplyView(self.config, self.bot, slug),
                        message_id=panel_msg_id,
                    )
                # Review views
                for user_id_str, review in assignment.get("active_reviews", {}).items():
                    review_msg_id = review.get("review_message_id")
                    if review_msg_id:
                        self.bot.add_view(
                            ReviewView(self.config, self.bot, slug, int(user_id_str), guild_id),
                            message_id=review_msg_id,
                        )

        # Close ticket views — iterate all members' open_tickets per guild
        for guild_id_str, guild_data in all_guild_data.items():
            guild_id = int(guild_id_str)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            staff_role_id = guild_data.get("ticket_staff_role")
            all_member_data = await self.config.all_members(guild)
            for member_id_str, member_data in all_member_data.items():
                for ticket in member_data.get("open_tickets", []):
                    close_msg_id = ticket.get("message_id")
                    channel_id = ticket.get("channel_id")
                    if close_msg_id and channel_id:
                        self.bot.add_view(
                            CloseTicketView(self.config, self.bot, channel_id, staff_role_id),
                            message_id=close_msg_id,
                        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Route DM replies to the application flow."""
        if message.guild is not None or message.author.bot:
            return
        if self.applications is None:
            return

        state = await self.config.user(message.author).active_application()
        if state is None:
            return

        guild = self.bot.get_guild(state["guild_id"])
        if guild is None:
            return

        member = guild.get_member(message.author.id)
        if member is None:
            return

        await self.applications._handle_application_reply(member, guild, state, message)

    @app_commands.guild_only()
    @commands.guild_only()
    @commands.hybrid_group(name="forms")
    async def forms_group(self, ctx: commands.Context) -> None:
        """Manage the Forms cog — tickets and application forms.

        Use `forms setup` for first-time configuration, or `forms settings`
        to adjust options after setup. Both commands require administrator or
        staff role permissions.
        """

    @forms_group.command(name="fixbuttons")
    @commands.admin_or_permissions(administrator=True)
    async def forms_fixbuttons(self, ctx: commands.Context) -> None:
        """Re-attach buttons to all active bot messages in this server (admins only).

        Fixes the ticket panel, open ticket close buttons, application Apply buttons,
        and pending review Approve/Deny buttons. Run this after a bot restart if
        buttons show as unresponsive. Already-closed log threads are not touched.
        """
        from .views import TicketPanelView, CloseTicketView, ApplyView, ReviewView

        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        guild_conf = self.config.guild(guild)
        fixed = 0
        skipped = 0

        # Ticket panel
        ticket_channel_id = await guild_conf.ticket_channel()
        panel_msg_id = await guild_conf.ticket_panel_message()
        if ticket_channel_id and panel_msg_id:
            channel = guild.get_channel(ticket_channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(panel_msg_id)
                    view = TicketPanelView(self.config, self.bot)
                    self.bot.add_view(view, message_id=panel_msg_id)
                    await msg.edit(view=view)
                    fixed += 1
                except Exception:
                    skipped += 1

        # Open ticket close buttons
        staff_role_id = await guild_conf.ticket_staff_role()
        all_member_data = await self.config.all_members(guild)
        for member_data in all_member_data.values():
            for ticket in member_data.get("open_tickets", []):
                channel_id = ticket.get("channel_id")
                msg_id = ticket.get("message_id")
                if not channel_id or not msg_id:
                    continue
                channel = guild.get_channel(channel_id)
                if not channel:
                    skipped += 1
                    continue
                try:
                    msg = await channel.fetch_message(msg_id)
                    view = CloseTicketView(self.config, self.bot, channel_id, staff_role_id)
                    self.bot.add_view(view, message_id=msg_id)
                    await msg.edit(view=view)
                    fixed += 1
                except Exception:
                    skipped += 1

        # Application Apply buttons and pending review buttons
        assignments = await guild_conf.application_assignments()
        for slug, assignment in assignments.items():
            # Apply panel button
            channel_id = assignment.get("channel_id")
            apply_msg_id = assignment.get("panel_message_id")
            if channel_id and apply_msg_id:
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        msg = await channel.fetch_message(apply_msg_id)
                        view = ApplyView(self.config, self.bot, slug)
                        self.bot.add_view(view, message_id=apply_msg_id)
                        await msg.edit(view=view)
                        fixed += 1
                    except Exception:
                        skipped += 1

            # Pending review Approve/Deny buttons (skip archived/locked threads)
            for user_id_str, review in assignment.get("active_reviews", {}).items():
                thread_id = review.get("thread_id")
                review_msg_id = review.get("review_message_id")
                if not thread_id or not review_msg_id:
                    continue
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                    if getattr(thread, "archived", False) or getattr(thread, "locked", False):
                        skipped += 1
                        continue
                    msg = await thread.fetch_message(review_msg_id)
                    view = ReviewView(self.config, self.bot, slug, int(user_id_str), guild.id)
                    self.bot.add_view(view, message_id=review_msg_id)
                    await msg.edit(view=view)
                    fixed += 1
                except Exception:
                    skipped += 1

        parts = [f"✅ Fixed **{fixed}** button(s)."]
        if skipped:
            parts.append(f"⚠️ {skipped} skipped (message deleted or thread already closed).")
        await ctx.send(" ".join(parts), ephemeral=True)

    @forms_group.command(name="setup")
    @commands.admin_or_permissions(administrator=True)
    async def forms_setup(self, ctx: commands.Context) -> None:
        """Run the first-time setup wizard (admins only).

        Walks through a 5-step interactive wizard to configure tickets:

        Step 1 — Ticket channel: where the Open Ticket panel button is posted.
        Step 2 — Ticket category: the Discord category where private ticket channels are created.
        Step 3 — Staff role: the role that can close tickets and access the settings panel.
        Step 4 — Ticket forum: the forum channel where closed ticket transcripts are archived
                  (a TICKET tag is created automatically).
        Step 5 — Categories & limits: ticket category names (one per line) and the max
                  number of open tickets per user.

        Once the wizard completes, the Open Ticket panel is posted to the configured channel.
        Re-running setup overwrites existing ticket settings — use `forms settings` for
        targeted changes. Application review forums are configured per-application via
        Assign to Channel in settings, not here.

        Each wizard step has a 5-minute timeout.
        """
        view = WizardStep1View(self.config, ctx.guild.id, self.bot)
        embed = discord.Embed(
            title="Forms Setup — Step 1 of 5",
            description="Select the **ticket channel** where the Open Ticket button will be posted.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=view)

    @forms_group.command(name="settings")
    async def forms_settings(self, ctx: commands.Context) -> None:
        """Open the settings panel (staff and admins).

        Displays a two-section settings panel:

        **Ticket Settings**
        - Change Ticket Channel — re-point the Open Ticket panel to a different channel.
        - Edit Categories — update the ticket category names shown to users.
        - Set Max Tickets — change the per-user open ticket limit (1–20).
        - Re-post Ticket Panel — re-posts the Open Ticket embed if it was deleted or lost.

        **Application Settings**
        - Create Application — opens a name/description modal, then walks you through
          adding questions via DM (up to 50 questions). Each question has a 10-minute window.
        - Edit Application — select an existing application and update its questions via DM.
          Each question has a 5-minute reply window.
        - Delete Application — permanently removes an application template and deletes its
          Apply button from the channel it was assigned to.
        - Manage Assignments — view, edit, or remove existing channel assignments.
          Shows the current review forum, role settings, and reviewer roles for each.
          Edit runs a 5-step update wizard; Remove deletes the Apply button from the channel.
        - Assign to Channel — posts an Apply button embed to a channel via a 7-step wizard:
          (1) application, (2) channel, (3) review forum, (4) approval role, (5) removal role,
          (6) required role, (7) additional reviewer roles. Staff can always approve/deny;
          reviewer roles extend that to department leads or other non-staff roles.

        Cooldowns are set per-denial in the Deny modal, not during assignment.
        """
        # Dynamic staff role permission check
        staff_role_id = await self.config.guild(ctx.guild).ticket_staff_role()
        is_admin = ctx.author.guild_permissions.administrator
        has_staff_role = staff_role_id and any(r.id == staff_role_id for r in ctx.author.roles)
        if not is_admin and not has_staff_role:
            await ctx.send("⚠️ You don't have permission to use this command.", ephemeral=True)
            return

        from .views import SettingsPanelView
        view = SettingsPanelView(self.config, self.bot)
        embed = discord.Embed(
            title="⚙️ Forms Settings",
            description="Select a section to configure:",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=view)

    async def red_get_data_for_user(self, *, requester: str, user_id: int) -> dict:
        """Return all stored data for a user (required by RedBot)."""
        data = {}
        user = self.bot.get_user(user_id) or discord.Object(id=user_id)
        user_data = await self.config.user(user).all()
        if any(v is not None and v != {} and v != [] for v in user_data.values()):
            data["user_config"] = user_data
        return data

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        """Delete all stored data for a user (required by RedBot)."""
        user = self.bot.get_user(user_id) or discord.Object(id=user_id)
        await self.config.user(user).clear()

        # Also clear member-scoped data across all guilds
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member:
                await self.config.member(member).clear()
