"""Main Forms cog class."""
from __future__ import annotations
import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from .tickets import TicketManager
from .applications import ApplicationManager


class Forms(commands.Cog):
    """Discord-native tickets and application forms."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x666F726D73, force_registration=True)
        self.tickets = TicketManager(bot, self.config)
        self.applications: ApplicationManager | None = None  # set in initialize()

    async def initialize(self) -> None:
        """Called after cog is added to bot. Registers config and persistent views."""
        pass

    @commands.group(name="forms")
    @commands.guild_only()
    async def forms_group(self, ctx: commands.Context) -> None:
        """Forms cog commands."""

    @forms_group.command(name="setup")
    @commands.admin_or_permissions(administrator=True)
    async def forms_setup(self, ctx: commands.Context) -> None:
        """Run the first-time setup wizard."""
        pass

    @forms_group.command(name="settings")
    # Permission check is dynamic (reads ticket_staff_role from Config at runtime).
    # Enforced inside the command body, not via decorator, since the role ID is guild-specific.
    async def forms_settings(self, ctx: commands.Context) -> None:
        """Open the settings panel."""
        pass

    async def red_get_data_for_user(self, *, requester, user_id: int):
        return {}

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        pass
