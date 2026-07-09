"""Main Filecab cog class."""
from __future__ import annotations
import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from .template_manager import TemplateManager
from .github_client import GitHubClient
from .publisher import DocumentPublisher
from .filing import FilingManager


class Filecab(commands.Cog):
    """Discord-native DOJ document filing."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x66696C65636162, force_registration=True)
        self.templates = TemplateManager(cog_data_path(self))
        self.github = GitHubClient(bot)
        self.publisher = DocumentPublisher(self.config, self.github)
        self.filing = FilingManager(bot, self.config, self.templates, self.publisher)

    async def initialize(self) -> None:
        """Register config defaults, load templates, and re-register persistent views."""
        self.config.register_guild(
            document_channel=None,
            document_review_channel=None,
            approval_role=None,
            panel_message_id=None,
            published_documents={},
            # {filing_id: {template_id, title, category, user_id, answers, filed_date, status,
            #              thread_id?, message_id?, discussion, approved_by?, signed_date?,
            #              signed_by?, html_path?, json_path?, published_url?}}
            # discussion is a list of {author_id, author_label, content, at} — every human
            # message posted in the filing's private review thread (filer included), kept
            # even if the thread itself is later archived/deleted.
            template_access={},
            # {template_id: [role_id, ...]} — templates not listed here (or
            # mapped to an empty list) are open to everyone. Only checked on
            # the public document panel; `filecab file` (staff) always
            # bypasses it. Admins always bypass it too.
        )
        self.config.register_user(
            active_filing=None,
            # {"template_id": str, "guild_id": int, "field_index": int, "answers": {}}
        )
        self.config.register_global(
            filing_counters={},
            # {"<template_id>-<year>": int} — used to mint "<template_id>-<year>-<seq>" filing ids
            site_repo=None,       # "owner/repo" — serves as both the templates source and publish target
            site_branch="main",
            site_base_url=None,  # optional override; defaults to https://{owner}.github.io/{repo}
        )
        self.templates.initialize()
        await self._register_persistent_views()

    async def cog_unload(self) -> None:
        await self.github.close()

    async def _register_persistent_views(self) -> None:
        """Re-register all persistent views after bot restart."""
        from .views import (
            TemplateSelectView,
            FilingReviewView,
            ApprovedDocumentView,
            SignerRequestView,
            build_template_options,
        )

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

            for filing_id, record in guild_data.get("published_documents", {}).items():
                spec = self.templates.get(record.get("template_id"))
                message_id = record.get("message_id")
                if record.get("status") == "pending" and message_id:
                    self.bot.add_view(
                        FilingReviewView(self.config, self.bot, filing_id, spec, record.get("signers", {})),
                        message_id=message_id,
                    )
                elif record.get("status") == "approved" and message_id:
                    self.bot.add_view(
                        ApprovedDocumentView(filing_id),
                        message_id=message_id,
                    )

                for role, signer_state in record.get("signers", {}).items():
                    dm_message_id = signer_state.get("dm_message_id")
                    if signer_state.get("status") == "pending" and dm_message_id:
                        self.bot.add_view(
                            SignerRequestView(filing_id, role, guild_id),
                            message_id=dm_message_id,
                        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Route DM replies to the filing flow, and log review-thread conversation."""
        if message.author.bot:
            return

        if message.guild is None:
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
            return

        if isinstance(message.channel, discord.Thread) and message.type == discord.MessageType.default:
            await self.filing.log_thread_message(message.guild, message.channel, message)

    def _is_staff(self, ctx: commands.Context, approval_role_id: int | None) -> bool:
        if ctx.author.guild_permissions.administrator:
            return True
        return bool(approval_role_id) and any(r.id == approval_role_id for r in ctx.author.roles)

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

        Walks through a 4-step interactive wizard:

        Step 1 — Document channel: where the document-type select panel is posted.
        Step 2 — Review channel: a text channel where each filing gets its own
                  private thread with Approve/Deny buttons. The filer is added to
                  their own thread so staff can ask follow-up questions directly —
                  they can't see any other filing's thread. The bot needs the
                  **Create Private Threads** permission there, and staff need
                  **Manage Threads** on that channel to see every filing's thread
                  without being added to each one individually.
        Step 3 — Approval role: who (besides admins) can approve/deny filings and
                  make them public.
        Step 4 — Site repository: the GitHub repo (`owner/repo`) that serves as
                  both the templates source and the publish destination — same
                  structure as the site itself. Templates are fetched from it
                  immediately. Publishing also needs a GitHub token set via Red's
                  own `[p]set api github token,<token>` (not asked here).

        Every filing always requires staff approval, and approving only files it
        (paper trail) — a separate "Make Public" action puts it on the live site.

        Re-running setup overwrites existing settings.
        """
        from .views import WizardStep1View

        view = WizardStep1View(self.config, ctx.guild.id, self.bot)
        embed = discord.Embed(
            title="Filecab Setup — Step 1 of 4",
            description="Select the **document channel** where the filing panel will be posted.",
            color=discord.Color.blurple(),
        )
        view.message = await ctx.send(embed=embed, view=view)

    @filecab_group.command(name="settings")
    async def filecab_settings(self, ctx: commands.Context) -> None:
        """Open the settings panel (staff and admins).

        Lets you change the document channel, review channel, approval role, and
        site repository; reload templates already on disk; re-post the document
        panel; restrict which roles can file particular templates; and take
        down or permanently delete previously filed documents. Use `filecab
        refresh` to fetch fresh templates from the site repo.
        """
        approval_role_id = await self.config.guild(ctx.guild).approval_role()
        if not self._is_staff(ctx, approval_role_id):
            await ctx.send("⚠️ You don't have permission to use this command.", ephemeral=True)
            return

        from .views import SettingsPanelView

        view = SettingsPanelView(self.config, self.bot)
        embed = discord.Embed(title="⚙️ Filecab Settings", color=discord.Color.blurple())
        view.message = await ctx.send(embed=embed, view=view, ephemeral=True)

    @filecab_group.command(name="file")
    async def filecab_file(self, ctx: commands.Context) -> None:
        """File any document type yourself, including judge-authored ones (staff and admins).

        Judge-authored templates (e.g. Order to Release, Warrant of Execution) have
        no citizen-applicant role and never appear on the public document panel —
        this is how staff file one. You can also use this to file a citizen-facing
        template on someone's behalf if needed.
        """
        approval_role_id = await self.config.guild(ctx.guild).approval_role()
        if not self._is_staff(ctx, approval_role_id):
            await ctx.send("⚠️ You don't have permission to use this command.", ephemeral=True)
            return

        from .views import StaffFileSelectView, build_template_options

        options = build_template_options(self, include_staff_authored=True)
        if not options:
            await ctx.send("No templates are loaded yet.", ephemeral=True)
            return
        view = StaffFileSelectView(options)
        view.message = await ctx.send("Select a document type to file:", view=view, ephemeral=True)

    @filecab_group.command(name="templates")
    async def filecab_templates(self, ctx: commands.Context) -> None:
        """List currently loaded document templates (local only — no network call).

        Use `filecab refresh` to fetch fresh/updated templates from the site repo.
        """
        templates = self.templates.reload()
        if not templates:
            await ctx.send(
                "No templates loaded yet. Run `filecab refresh` to fetch them from "
                "the configured site repo."
            )
            return
        listing = "\n".join(f"• {spec['title']} (`{tid}`)" for tid, spec in templates.items())
        await ctx.send(f"**{len(templates)}** template(s) loaded:\n{listing}")

    @filecab_group.command(name="refresh")
    async def filecab_refresh(self, ctx: commands.Context) -> None:
        """Fetch the latest templates from the configured site repo (staff and admins)."""
        approval_role_id = await self.config.guild(ctx.guild).approval_role()
        if not self._is_staff(ctx, approval_role_id):
            await ctx.send("⚠️ You don't have permission to use this command.", ephemeral=True)
            return

        site_repo = await self.config.site_repo()
        if not site_repo or "/" not in site_repo:
            await ctx.send(
                "⚠️ No site repository configured yet — set one via `filecab setup` or "
                "`filecab settings`.",
                ephemeral=True,
            )
            return

        await ctx.defer()
        owner, repo = site_repo.split("/", 1)
        branch = await self.config.site_branch()
        count = await self.templates.refresh_from_repo(self.github, owner, repo, branch)
        if count:
            listing = "\n".join(
                f"• {spec['title']} (`{tid}`)" for tid, spec in self.templates.all_templates().items()
            )
            await ctx.send(f"🔄 Fetched **{count}** template(s) from `{site_repo}`:\n{listing}")
        else:
            await ctx.send(
                f"⚠️ Fetched 0 templates from `{site_repo}` — check the repo/branch are correct "
                "and the `templates/` folder exists there."
            )

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
