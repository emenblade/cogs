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
        """Re-register persistent views after bot restart. Implemented in Task 14."""
        pass

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

    async def red_get_data_for_user(self, *, requester, user_id: int):
        return {}

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        pass
