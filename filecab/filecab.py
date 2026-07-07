"""Main Filecab cog class."""
from __future__ import annotations
import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from .template_manager import TemplateManager
from .publisher import DocumentPublisher
from .filing import FilingManager


class Filecab(commands.Cog):
    """Discord-native DOJ document filing."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x66696C65636162, force_registration=True)
        self.templates = TemplateManager(cog_data_path(self))
        self.publisher = DocumentPublisher()
        self.filing = FilingManager(bot, self.config, self.templates, self.publisher)

    async def initialize(self) -> None:
        """Register config defaults, load templates, and re-register persistent views."""
        self.config.register_guild(
            document_channel=None,
            document_review_forum=None,
            approval_required=True,
            approval_role=None,
            panel_message_id=None,
            published_documents={},
            # {doc_id: {slug, output_dir, filename, user_id, status, thread_id?, message_id?}}
        )
        self.config.register_user(
            active_filing=None,
            # {"slug": str, "guild_id": int, "field_index": int, "answers": {}}
        )
        self.templates.initialize()
        await self._register_persistent_views()

    async def _register_persistent_views(self) -> None:
        """Re-register all persistent views after bot restart."""
        from .views import TemplateSelectView, FilingReviewView, build_template_options

        all_guild_data = await self.config.all_guilds()
        for guild_id_str, guild_data in all_guild_data.items():
            guild_id = int(guild_id_str)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue

            panel_msg_id = guild_data.get("panel_message_id")
            if panel_msg_id:
                options = build_template_options(self)
                if options:
                    self.bot.add_view(
                        TemplateSelectView(self.config, self.bot, options),
                        message_id=panel_msg_id,
                    )

            for doc_id, record in guild_data.get("published_documents", {}).items():
                if record.get("status") == "pending" and record.get("message_id"):
                    self.bot.add_view(
                        FilingReviewView(self.config, self.bot, doc_id),
                        message_id=record["message_id"],
                    )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Route DM replies to the document filing flow."""
        if message.guild is not None or message.author.bot:
            return

        state = await self.config.user(message.author).active_filing()
        if state is None:
            return

        guild = self.bot.get_guild(state["guild_id"])
        if guild is None:
            return

        member = guild.get_member(message.author.id)
        if member is None:
            return

        await self.filing.handle_reply(member, guild, state, message)

    @app_commands.guild_only()
    @commands.guild_only()
    @commands.hybrid_group(name="filecab")
    async def filecab_group(self, ctx: commands.Context) -> None:
        """Manage the Filecab cog — DOJ document filing.

        Use `filecab setup` for first-time configuration, or `filecab settings`
        to adjust options afterward. Both require administrator or staff role
        permissions.
        """

    @filecab_group.command(name="setup")
    @commands.admin_or_permissions(administrator=True)
    async def filecab_setup(self, ctx: commands.Context) -> None:
        """Run the first-time setup wizard (admins only).

        Walks through a 3-step interactive wizard:

        Step 1 — Document channel: where the document-type select panel is posted.
        Step 2 — Review forum: the forum channel where pending filings are posted
                  with Approve/Deny buttons.
        Step 3 — Approval role and toggle: who (besides admins) can approve or deny
                  filings, and whether approval is required before publishing.

        Once the wizard completes, the document panel is posted to the configured
        channel — but only if at least one template is already loaded. Drop template
        HTML+JSON pairs into the cog's data folder (see docs/TECHNICAL.md) beforehand,
        or re-post the panel later from `filecab settings`.

        Re-running setup overwrites existing settings.
        """
        from .views import WizardStep1View

        view = WizardStep1View(self.config, ctx.guild.id, self.bot)
        embed = discord.Embed(
            title="Filecab Setup — Step 1 of 3",
            description="Select the **document channel** where the filing panel will be posted.",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, view=view)

    @filecab_group.command(name="settings")
    async def filecab_settings(self, ctx: commands.Context) -> None:
        """Open the settings panel (staff and admins).

        Lets you change the document channel, review forum, and approval role;
        toggle whether approval is required; reload templates from disk after
        adding new HTML+JSON pairs; re-post the document panel; and take down
        previously published documents.
        """
        approval_role_id = await self.config.guild(ctx.guild).approval_role()
        is_admin = ctx.author.guild_permissions.administrator
        has_role = approval_role_id and any(r.id == approval_role_id for r in ctx.author.roles)
        if not is_admin and not has_role:
            await ctx.send("⚠️ You don't have permission to use this command.", ephemeral=True)
            return

        from .views import SettingsPanelView

        view = SettingsPanelView(self.config, self.bot)
        embed = discord.Embed(title="⚙️ Filecab Settings", color=discord.Color.blurple())
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @filecab_group.command(name="templates")
    async def filecab_templates(self, ctx: commands.Context) -> None:
        """List currently loaded document templates and reload them from disk."""
        templates = self.templates.reload()
        if not templates:
            await ctx.send(
                "No templates loaded. Drop HTML+JSON template pairs into the cog's data "
                "folder — see docs/TECHNICAL.md for the format."
            )
            return
        listing = "\n".join(f"• {spec.get('name', slug)} (`{slug}`)" for slug, spec in templates.items())
        await ctx.send(f"🔄 **{len(templates)}** template(s) loaded:\n{listing}")

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
