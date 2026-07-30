"""Main Filecab cog class."""
from __future__ import annotations
import asyncio
import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from .template_manager import TemplateManager
from .github_client import GitHubClient
from .publisher import DocumentPublisher
from .filing import FilingManager

_HEARTBEAT_INTERVAL = 600
_GUILD_REPAIR_DELAY = 2


class Filecab(commands.Cog):
    """Discord-native DOJ document filing."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x66696C65636162, force_registration=True)
        self.templates = TemplateManager(cog_data_path(self))
        self.github = GitHubClient(bot)
        self.publisher = DocumentPublisher(self.config, self.github)
        self.filing = FilingManager(bot, self.config, self.templates, self.publisher)
        self._heartbeat_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        """Register config defaults, load templates, and re-register persistent views."""
        self.config.register_guild(
            document_channel=None,
            document_review_category=None,
            document_log_forum=None,
            approval_role=None,
            panel_message_id=None,
            published_documents={},
            # {filing_id: {template_id, title, category, user_id, answers, filed_date, status,
            #              channel_id?, message_id?, discussion, approved_by?, signed_date?,
            #              signed_by?, html_path?, json_path?, published_url?, archived_thread_id?}}
            # discussion is a list of {author_id, author_label, content, at} — every human
            # message posted in the filing's private review channel (filer included), kept
            # even if the channel itself is later deleted. archived_thread_id is set once
            # Make Public archives the channel's full history to document_log_forum and
            # deletes it — entirely optional, see "Archiving & channel cleanup" below.
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
        self._start_heartbeat()

    async def cog_unload(self) -> None:
        self._stop_heartbeat()
        await self.github.close()

    async def _register_persistent_views(self) -> None:
        """Re-register all persistent views after bot restart."""
        from .views import (
            TemplateSelectView,
            FilingReviewView,
            ApprovedDocumentView,
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

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._view_heartbeat())

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _view_heartbeat(self) -> None:
        await self.bot.wait_until_red_ready()
        while True:
            try:
                all_guild_data = await self.config.all_guilds()
                for guild_id_str in all_guild_data:
                    guild = self.bot.get_guild(int(guild_id_str))
                    if guild is None:
                        continue
                    try:
                        await self._repair_guild_views(guild)
                    except Exception:
                        pass
                    await asyncio.sleep(_GUILD_REPAIR_DELAY)
            except Exception:
                pass
            await asyncio.sleep(_HEARTBEAT_INTERVAL)

    async def _repair_guild_views(self, guild: discord.Guild) -> tuple[int, int]:
        from .views import (
            TemplateSelectView, FilingReviewView, ApprovedDocumentView,
            build_template_options,
        )

        guild_conf = self.config.guild(guild)
        fixed = 0
        skipped = 0

        panel_msg_id = await guild_conf.panel_message_id()
        if panel_msg_id:
            channel_id = await guild_conf.document_channel()
            channel = guild.get_channel(channel_id) if channel_id else None
            if channel:
                try:
                    msg = await channel.fetch_message(panel_msg_id)
                    options = build_template_options(self)
                    if options:
                        view = TemplateSelectView(self.config, self.bot, options)
                        self.bot.add_view(view, message_id=panel_msg_id)
                        await msg.edit(view=view)
                        fixed += 1
                    else:
                        skipped += 1
                except Exception:
                    skipped += 1

        published = await guild_conf.published_documents()
        for filing_id, record in published.items():
            spec = self.templates.get(record.get("template_id"))
            msg_id = record.get("message_id")
            channel_id = record.get("channel_id")
            channel = guild.get_channel(channel_id) if channel_id else None
            if not channel or not msg_id:
                skipped += 1
                continue
            try:
                msg = await channel.fetch_message(msg_id)
                if record.get("status") == "pending":
                    view = FilingReviewView(
                        self.config, self.bot, filing_id, spec,
                        record.get("signers", {}),
                    )
                    self.bot.add_view(view, message_id=msg_id)
                    await msg.edit(view=view)
                    fixed += 1
                elif record.get("status") == "approved":
                    view = ApprovedDocumentView(filing_id)
                    self.bot.add_view(view, message_id=msg_id)
                    await msg.edit(view=view)
                    fixed += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1

        return fixed, skipped

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Route DM replies to the filing flow, and log review-channel conversation."""
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

        if isinstance(message.channel, discord.TextChannel) and message.type == discord.MessageType.default:
            await self.filing.log_review_message(message.guild, message.channel, message)

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
        Step 2 — Review category: a **category**, not a channel. Each filing gets
                  its own private text channel created under it, with Approve/Deny
                  buttons, staff able to see it via the category's own permissions,
                  and the filer added via a channel-specific permission overwrite —
                  same mechanism as the `forms` cog's ticket channels, not threads
                  (threads turned out not to reliably grant a non-member access no
                  matter what permission the bot had). The category needs
                  `@everyone` denied View Channel and your staff role granted it,
                  same as you'd lock down any staff-only space; the bot's role
                  needs **Manage Channels** and **Manage Roles** on the category
                  (to create channels there with per-member overwrites) — if
                  your `forms` ticket category already works, the bot's
                  permissions there are the reference to copy.
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

        Lets you change the document channel, review category, log forum,
        approval role, and site repository; reload templates already on disk;
        re-post the document panel; restrict which roles can file particular
        templates; and take down or permanently delete previously filed
        documents. Use `filecab refresh` to fetch fresh templates from the
        site repo.

        Setting a log forum is optional — if configured, Make Public archives
        a filing's whole review channel there (locked, tagged by category)
        and deletes the channel a couple minutes later; if it's never set,
        review channels are simply left as-is after publishing, same as
        before this existed.
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

    @filecab_group.command(name="fixbuttons")
    @commands.admin_or_permissions(administrator=True)
    async def filecab_fixbuttons(self, ctx: commands.Context) -> None:
        """Re-attach buttons to all bot messages in this server (admins only).

        Fixes the document panel select, pending review Approve/Deny/Sign buttons,
        and approved-document Make Public buttons. Run this after a bot restart if
        buttons show as unresponsive.

        The heartbeat also runs this automatically every 10 minutes, so you
        shouldn't normally need to run it manually.
        """
        await ctx.defer(ephemeral=True)
        fixed, skipped = await self._repair_guild_views(ctx.guild)
        parts = [f"✅ Fixed **{fixed}** button(s)."]
        if skipped:
            parts.append(f"⚠️ {skipped} skipped (message deleted or channel gone).")
        await ctx.send(" ".join(parts), ephemeral=True)

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

    @filecab_group.command(name="nuke")
    @commands.is_owner()
    async def filecab_nuke(self, ctx: commands.Context) -> None:
        """Permanently wipe all filing test data for this server (bot owner only).

        Deletes every channel in the configured review category, every thread in
        the configured log forum, every published document on the site repo, and
        every filing record — meant to reset a test server to a clean slate before
        going live. Templates and every other setting (channels, roles, site repo)
        are left untouched. Also resets the filing ID counter, which is shared
        bot-wide across every server this bot is in.

        Irreversible — asks for a confirmation password in chat before doing
        anything, and cancels if it's wrong or if you don't reply in time.
        """
        guild_conf = self.config.guild(ctx.guild)
        published = await guild_conf.published_documents()

        category_id = await guild_conf.document_review_category()
        category = ctx.guild.get_channel(category_id) if category_id else None
        channel_count = len(category.channels) if isinstance(category, discord.CategoryChannel) else 0

        log_forum_id = await guild_conf.document_log_forum()
        log_forum = ctx.guild.get_channel(log_forum_id) if log_forum_id else None
        thread_count = 0
        if isinstance(log_forum, discord.ForumChannel):
            thread_count = len(log_forum.threads)
            try:
                async for _ in log_forum.archived_threads(limit=None):
                    thread_count += 1
            except discord.HTTPException:
                pass

        embed = discord.Embed(
            title="☢️ Nuke Filing Data",
            description=(
                "This will **permanently delete**:\n"
                f"• **{len(published)}** filing record(s)\n"
                f"• **{channel_count}** channel(s) in the review category\n"
                f"• **{thread_count}** thread(s) in the log forum\n"
                "• Every published document on the site repo\n"
                "• The filing ID counter (bot-wide — affects every server this bot serves)\n\n"
                "Templates and every other setting are kept.\n\n"
                "**This cannot be undone.** Reply with the confirmation password "
                "within 60 seconds to proceed, or anything else to cancel."
            ),
            color=discord.Color.red(),
        )
        await ctx.send(embed=embed)

        def check(m: discord.Message) -> bool:
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out — nothing was deleted.")
            return

        if reply.content.strip().lower() != "canada":
            await ctx.send("❌ Incorrect password — nothing was deleted.")
            return

        await ctx.send("☢️ Confirmed — wiping filing data now, this may take a moment...")
        summary = await self.filing.wipe_guild_data(ctx.guild)

        failures = ""
        if summary["channels_failed"]:
            failures += f" ({summary['channels_failed']} failed)"
        thread_failures = f" ({summary['threads_failed']} failed)" if summary["threads_failed"] else ""

        await ctx.send(
            "✅ **Wipe complete.**\n"
            f"• Filing records cleared: **{summary['records']}**\n"
            f"• Local document files deleted: **{summary['local_files']}**\n"
            f"• Published GitHub files removed: **{summary['github_files']}**\n"
            f"• Review channels deleted: **{summary['channels_deleted']}**{failures}\n"
            f"• Log forum threads deleted: **{summary['threads_deleted']}**{thread_failures}\n"
            "• Filing ID counter reset."
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
