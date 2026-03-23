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

    @forms_group.command(name="setup")
    @commands.admin_or_permissions(administrator=True)
    async def forms_setup(self, ctx: commands.Context) -> None:
        """Run the first-time setup wizard (admins only).

        Walks through a 7-step interactive wizard to configure the cog:

        Step 1 — Ticket channel: the channel where the "Open Ticket" panel button is posted.
        Step 2 — Ticket category: the Discord category under which private ticket channels are created.
        Step 3 — Ticket user role: the role a member must have to open tickets.
        Step 4 — Staff role: the role that can close tickets and access the settings panel.
        Step 5 — Staff forum: the forum channel where closed ticket transcripts and application reviews are archived.
        Step 6 — Forum tags: TICKET and APPLICATION tags are created automatically in the chosen forum.
        Step 7 — Categories & limits: up to 5 ticket category names and the max number of open tickets per user.

        Once the wizard completes, the ticket panel embed is posted to the configured channel.
        Re-running setup overwrites existing settings — use `forms settings` for targeted changes.

        Each wizard step has a 5-minute timeout. If you don't interact within that window
        the wizard will expire and you'll need to run the command again.
        """
        view = WizardStep1View(self.config, ctx.guild.id, self.bot)
        embed = discord.Embed(
            title="Forms Setup — Step 1 of 7",
            description="Select the **ticket channel** where the Open Ticket button will be posted.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=view)

    @forms_group.command(name="settings")
    async def forms_settings(self, ctx: commands.Context) -> None:
        """Open the settings panel (staff and admins).

        Displays a two-section settings panel:

        **Ticket Settings**
        - Change Ticket Channel — re-point the panel to a different channel.
        - Edit Categories — update the ticket category names shown to users.
        - Set Max Tickets — change the per-user open ticket limit (1–20).
        - Re-post Ticket Panel — use this if the panel message was deleted or lost.

        **Application Settings**
        - Create Application — opens a name/description modal, then walks you through
          adding questions via DM (up to 50). Each question has a 10-minute reply window.
        - Edit Application — select an existing application and update its questions via DM.
          Each question has a 5-minute reply window.
        - Delete Application — permanently removes an application template.
        - Assign to Channel — posts an Apply button embed to a channel, selecting which
          application, which approval role to grant on approval, and the re-application cooldown.

        The settings panel itself has a 3-minute inactivity timeout.
        """
        # Dynamic staff role permission check
        staff_role_id = await self.config.guild(ctx.guild).ticket_staff_role()
        is_admin = ctx.author.guild_permissions.administrator
        has_staff_role = staff_role_id and any(r.id == staff_role_id for r in ctx.author.roles)
        if not is_admin and not has_staff_role:
            await ctx.send("You don't have permission to use this command.", ephemeral=True)
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
