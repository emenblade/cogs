"""Main Forms cog class."""
from __future__ import annotations
import discord
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
        from .views import TicketPanelView, CloseTicketView, ApplyView, ReviewView, ResetCooldownView

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
                # Review views (active)
                for user_id_str, review in assignment.get("active_reviews", {}).items():
                    review_msg_id = review.get("review_message_id")
                    if review_msg_id:
                        self.bot.add_view(
                            ReviewView(self.config, self.bot, slug, int(user_id_str), guild_id),
                            message_id=review_msg_id,
                        )
                # Reset cooldown views (closed reviews)
                for user_id_str, reset_msg_id in assignment.get("reset_cooldown_messages", {}).items():
                    if reset_msg_id:
                        self.bot.add_view(
                            ResetCooldownView(self.config, self.bot, slug, int(user_id_str)),
                            message_id=reset_msg_id,
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

    @commands.group(name="forms")
    @commands.guild_only()
    async def forms_group(self, ctx: commands.Context) -> None:
        """Forms cog commands."""

    @forms_group.command(name="setup")
    @commands.admin_or_permissions(administrator=True)
    async def forms_setup(self, ctx: commands.Context) -> None:
        """Run the first-time setup wizard."""
        view = WizardStep1View(self.config, ctx.guild.id, self.bot)
        embed = discord.Embed(
            title="Forms Setup — Step 1 of 7",
            description="Select the **ticket channel** where the Open Ticket button will be posted.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=view)

    @forms_group.command(name="settings")
    async def forms_settings(self, ctx: commands.Context) -> None:
        """Open the settings panel."""
        # Dynamic staff role permission check
        staff_role_id = await self.config.guild(ctx.guild).ticket_staff_role()
        is_admin = ctx.author.guild_permissions.administrator
        has_staff_role = staff_role_id and any(r.id == staff_role_id for r in ctx.author.roles)
        if not is_admin and not has_staff_role:
            await ctx.send("You don't have permission to use this command.", delete_after=10)
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
