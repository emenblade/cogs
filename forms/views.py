"""All Discord UI views, modals, and components for the Forms cog."""
from __future__ import annotations
import discord
from redbot.core import Config
from .utils import check_staff_role


async def _check_reviewer(interaction: discord.Interaction, config: Config, slug: str) -> bool:
    """Return True if the user has the staff role or a reviewer role for this application."""
    guild_conf = config.guild(interaction.guild)
    staff_role_id = await guild_conf.ticket_staff_role()
    assignments = await guild_conf.application_assignments()
    reviewer_role_ids = assignments.get(slug, {}).get("reviewer_role_ids", [])
    member_role_ids = {r.id for r in getattr(interaction.user, "roles", [])}
    if staff_role_id and staff_role_id in member_role_ids:
        return True
    return any(rid in member_role_ids for rid in reviewer_role_ids)


class _WizardStepView(discord.ui.View):
    """Base class for wizard steps."""

    def __init__(self, config: Config, guild_id: int, bot):
        super().__init__(timeout=300)
        self.config = config
        self.guild_id = guild_id
        self.bot = bot
        self._selected = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class WizardStep1View(_WizardStepView):
    """Step 1: Select ticket channel."""

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select the ticket channel…",
        channel_types=[discord.ChannelType.text],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("Please select a channel first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).ticket_channel.set(self._selected.id)
        self.stop()
        await _send_wizard_step2(interaction, self.config, self.guild_id, self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep2View(_WizardStepView):
    """Step 2: Select ticket category."""

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select the ticket category…",
        channel_types=[discord.ChannelType.category],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("Please select a category first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).ticket_category.set(self._selected.id)
        self.stop()
        await _send_wizard_step4(interaction, self.config, self.guild_id, self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)



class WizardStep4View(_WizardStepView):
    """Step 3: Select ticket staff role."""

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select the ticket staff role…",
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("Please select a role first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).ticket_staff_role.set(self._selected.id)
        self.stop()
        await _send_wizard_step5(interaction, self.config, self.guild_id, self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep5View(_WizardStepView):
    """Step 4: Select ticket forum channel."""

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select the staff forum channel…",
        channel_types=[discord.ChannelType.forum],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("Please select a forum first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).ticket_forum.set(self._selected.id)
        self.stop()
        # ChannelSelect returns AppCommandChannel, not a real ForumChannel — resolve it
        resolved = interaction.guild.get_channel(self._selected.id)
        if resolved and isinstance(resolved, discord.ForumChannel):
            await _ensure_forum_tags(resolved, self.config, self.guild_id)
        await _send_wizard_step7(interaction, self.config, self.guild_id, self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class TicketCategoriesModal(discord.ui.Modal, title="Ticket Categories"):
    """Modal for entering ticket category names and max open tickets."""

    categories = discord.ui.TextInput(
        label="Categories (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="General Support\nBug Report\nBilling",
        required=True,
        max_length=500,
    )
    max_open = discord.ui.TextInput(
        label="Max open tickets per user",
        placeholder="3",
        required=False,
        max_length=2,
    )

    def __init__(self, config: Config, guild_id: int, bot,
                 existing_cats: list[str] | None = None, existing_max: int | None = None):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.bot = bot
        if existing_cats:
            self.categories.default = "\n".join(existing_cats)
        if existing_max is not None:
            self.max_open.default = str(existing_max)

    async def on_submit(self, interaction: discord.Interaction):
        cats = [c.strip() for c in self.categories.value.splitlines() if c.strip()]
        max_open = max(1, int(self.max_open.value)) if self.max_open.value.strip().isdigit() else 3
        await self.config.guild_from_id(self.guild_id).ticket_categories.set(cats)
        await self.config.guild_from_id(self.guild_id).ticket_max_open.set(max_open)
        await finish_wizard(interaction, self.config, self.guild_id, self.bot)


class WizardStep7View(_WizardStepView):
    """Step 6: Enter ticket categories via modal."""

    @discord.ui.button(label="Enter Categories", style=discord.ButtonStyle.blurple)
    async def enter_categories(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        existing_cats = await self.config.guild_from_id(self.guild_id).ticket_categories()
        existing_max = await self.config.guild_from_id(self.guild_id).ticket_max_open()
        modal = TicketCategoriesModal(
            self.config, self.guild_id, self.bot,
            existing_cats=existing_cats or None,
            existing_max=existing_max,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


async def _ensure_forum_tags(forum: discord.ForumChannel, config: Config, guild_id: int) -> None:
    """Create TICKET tag in the ticket forum if it doesn't exist; store ID in config."""
    existing = {t.name: t for t in forum.available_tags}
    ticket_tag = existing.get("TICKET") or await forum.create_tag(name="TICKET")
    await config.guild_from_id(guild_id).ticket_tag_id.set(ticket_tag.id)


async def _send_wizard_step2(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep2View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 2 of 5",
        description="Select the **category** where ticket channels will be created.",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def _send_wizard_step4(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep4View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 3 of 5",
        description="Select the **staff role** that can manage and close tickets.",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def _send_wizard_step5(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep5View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 4 of 5",
        description="Select the **forum channel** where closed ticket transcripts will be archived.",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def _send_wizard_step7(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep7View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 5 of 5",
        description=(
            "Click **Enter Categories** to set your ticket category names (one per line) "
            "and the max open tickets per user."
        ),
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def finish_wizard(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    """Post the ticket panel in the configured channel and mark setup complete."""
    await interaction.response.defer(ephemeral=True)

    ticket_channel_id = await config.guild_from_id(guild_id).ticket_channel()
    guild = bot.get_guild(guild_id)
    channel = guild.get_channel(ticket_channel_id) if guild else None
    if channel is None:
        await interaction.followup.send(
            "⚠️ Could not find the configured ticket channel. Please re-run setup.",
            ephemeral=True,
        )
        return
    embed = discord.Embed(
        title="🎫 Open a Ticket",
        description="Click the button below to open a support ticket.",
        color=discord.Color.blurple(),
    )
    panel_view = TicketPanelView(config, bot)
    msg = await channel.send(embed=embed, view=panel_view)
    await config.guild_from_id(guild_id).ticket_panel_message.set(msg.id)
    await interaction.followup.send("✅ Setup complete! Ticket panel posted.", ephemeral=True)


class TicketPanelView(discord.ui.View):
    """Persistent view for the ticket channel panel."""

    def __init__(self, config: Config, bot):
        super().__init__(timeout=None)  # persistent
        self.config = config
        self.bot = bot

    @discord.ui.button(
        label="🎫 Open Ticket",
        style=discord.ButtonStyle.blurple,
        custom_id="forms:open_ticket",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_conf = self.config.guild(interaction.guild)

        # Category guard
        categories = await guild_conf.ticket_categories()
        if not categories:
            await interaction.response.send_message(
                "Tickets are not fully configured yet. Please contact staff.", ephemeral=True
            )
            return

        # Max tickets guard
        max_open = await guild_conf.ticket_max_open()
        open_tickets = await self.config.member(interaction.user).open_tickets()
        if len(open_tickets) >= max_open:
            await interaction.response.send_message(
                f"You already have {len(open_tickets)} open ticket(s). "
                f"Please wait for them to be resolved before opening a new one.",
                ephemeral=True,
            )
            return

        # Show category select
        view = TicketCategoryView(self.config, self.bot, categories)
        await interaction.response.send_message(
            "Please select a category for your ticket:", view=view, ephemeral=True
        )


class TicketCategoryView(discord.ui.View):
    """Ephemeral category select shown after clicking Open Ticket."""

    def __init__(self, config: Config, bot, categories: list[str]):
        super().__init__(timeout=120)
        self.config = config
        self.bot = bot
        options = [discord.SelectOption(label=c, value=c) for c in categories[:25]]
        self.add_item(self._CategorySelect(options))

    class _CategorySelect(discord.ui.Select):
        def __init__(self, options):
            super().__init__(placeholder="Select a category…", options=options)

        async def callback(self, interaction: discord.Interaction):
            from .tickets import TicketManager
            category = self.values[0]
            manager = TicketManager(interaction.client, interaction.client.cogs["Forms"].config)
            await interaction.response.edit_message(
                content="Creating your ticket…", view=None
            )
            await manager.create_ticket(interaction, category)


class CloseTicketView(discord.ui.View):
    """Persistent view posted in each ticket channel. Only staff can close."""

    def __init__(self, config: Config, bot, channel_id: int, staff_role_id: int | None):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.channel_id = channel_id
        self.staff_role_id = staff_role_id
        # Make custom_id unique per channel so Discord can distinguish buttons
        if self.children:
            self.children[0].custom_id = f"forms:close_ticket:{channel_id}"

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.red,
        custom_id="forms:close_ticket",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_staff_role(interaction, self.staff_role_id):
            await interaction.response.send_message(
                "Only staff can close tickets.", ephemeral=True
            )
            return
        from .tickets import TicketManager
        manager = TicketManager(interaction.client, self.config)
        await interaction.response.defer()
        await manager.close_ticket(interaction.channel, interaction.guild)


class CreateApplicationModal(discord.ui.Modal, title="Create Application"):
    app_name = discord.ui.TextInput(
        label="Application Name",
        placeholder="e.g. Mod Application",
        max_length=80,
    )
    description = discord.ui.TextInput(
        label="User-Facing Description",
        style=discord.TextStyle.paragraph,
        placeholder="What is this application for? Users will see this.",
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        self.result_name = self.app_name.value.strip()
        self.result_description = self.description.value.strip()
        await interaction.response.send_message(
            f"✅ Application **{self.result_name}** created. "
            "Check your DMs — I'll walk you through adding questions.",
            ephemeral=True,
        )


class ApplyView(discord.ui.View):
    """Persistent view with the Apply button posted in application channels."""

    def __init__(self, config: Config, bot, slug: str):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.slug = slug
        # Make custom_id unique per application slug
        if self.children:
            self.children[0].custom_id = f"forms:apply:{slug}"

    @discord.ui.button(
        label="📋 Apply",
        style=discord.ButtonStyle.green,
        custom_id="forms:apply:_placeholder",
    )
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        from .applications import ApplicationManager
        from redbot.core.data_manager import cog_data_path
        import time

        manager = ApplicationManager(
            interaction.client,
            self.config,
            cog_data_path(interaction.client.cogs["Forms"]),
        )

        # Check: already in progress?
        active = await self.config.user(interaction.user).active_application()
        if active is not None:
            await interaction.response.send_message(
                "You already have an application in progress. Please complete it first.",
                ephemeral=True,
            )
            return

        # Check: pending review?
        assignments = await self.config.guild(interaction.guild).application_assignments()
        app_conf = assignments.get(self.slug, {})
        if str(interaction.user.id) in app_conf.get("active_reviews", {}):
            await interaction.response.send_message(
                "Your application is currently awaiting staff review. "
                "Please be patient — this process can take a few days.",
                ephemeral=True,
            )
            return

        # Check: required role?
        required_role_id = app_conf.get("required_role_id")
        if required_role_id:
            member_roles = getattr(interaction.user, "roles", [])
            if not any(r.id == required_role_id for r in member_roles):
                role = interaction.guild.get_role(required_role_id)
                role_name = role.name if role else "a required role"
                await interaction.response.send_message(
                    f"You need the **{role_name}** role to apply for this.",
                    ephemeral=True,
                )
                return

        # Check: on cooldown?
        cooldowns = await self.config.user(interaction.user).application_cooldowns()
        expiry = cooldowns.get(self.slug)
        if expiry and time.time() < expiry:
            remaining = int(expiry - time.time())
            days, rem = divmod(remaining, 86400)
            hours = rem // 3600
            await interaction.response.send_message(
                f"You can re-apply in {days}d {hours}h.", ephemeral=True
            )
            return

        # Check: DMs open
        try:
            dm = await interaction.user.create_dm()
            await dm.send("Starting your application…")
        except discord.Forbidden:
            await interaction.response.send_message(
                "Please enable DMs from server members to apply.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "✅ Check your DMs! I've sent you the first question.", ephemeral=True
        )
        await manager.start_application(interaction.user, interaction.guild, self.slug, dm)


class DenyReasonModal(discord.ui.Modal, title="Denial Reason"):
    reason = discord.ui.TextInput(
        label="Reason for denial",
        style=discord.TextStyle.paragraph,
        placeholder="Please provide a clear reason for the applicant.",
        max_length=1000,
    )
    cooldown = discord.ui.TextInput(
        label="Cooldown days (0 = no cooldown)",
        placeholder="7",
        max_length=3,
        required=False,
    )

    def __init__(self, config, bot, slug, user_id, guild_id, thread, review_message_id: int):
        super().__init__()
        self.config = config
        self.bot = bot
        self.slug = slug
        self.user_id = user_id
        self.guild_id = guild_id
        self.thread = thread
        self.review_message_id = review_message_id

    async def on_submit(self, interaction: discord.Interaction):
        import time
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = guild.get_member(self.user_id) or await self.bot.fetch_user(self.user_id)

        try:
            cooldown_days = max(0, int(self.cooldown.value or "7"))
        except ValueError:
            cooldown_days = 7

        # DM the denial reason
        try:
            await user.send(
                f"Your **{self.slug.replace('-', ' ').title()}** application was not approved.\n\n"
                f"**Reason:** {self.reason.value}"
            )
        except discord.Forbidden:
            pass

        # Set cooldown if > 0
        if cooldown_days > 0:
            expiry = time.time() + cooldown_days * 86400
            cooldowns = await self.config.user(user).application_cooldowns()
            cooldowns[self.slug] = expiry
            await self.config.user(user).application_cooldowns.set(cooldowns)

        # Clean up active_reviews
        assignments = await self.config.guild(guild).application_assignments()
        if self.slug in assignments:
            assignments[self.slug]["active_reviews"].pop(str(self.user_id), None)
            await self.config.guild(guild).application_assignments.set(assignments)

        # Post denial message in thread
        cooldown_note = f" ({cooldown_days}d cooldown)" if cooldown_days > 0 else " (no cooldown set)"
        await self.thread.send(
            f"❌ **Denied** by {interaction.user.mention} — **Reason:** {self.reason.value}{cooldown_note}"
        )

        # Edit original review message to replace buttons with PostReviewView
        post_view = PostReviewView(self.config, self.bot, self.slug, self.user_id, self.guild_id)
        try:
            msg = await self.thread.fetch_message(self.review_message_id)
            await msg.edit(view=post_view)
        except Exception:
            pass

        await interaction.followup.send("❌ Application denied. User has been notified.", ephemeral=True)


class ReviewView(discord.ui.View):
    """Persistent view on the staff review forum post."""

    def __init__(self, config: Config, bot, slug: str, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.slug = slug
        self.user_id = user_id
        self.guild_id = guild_id
        # Unique custom_ids per review
        if len(self.children) >= 2:
            self.children[0].custom_id = f"forms:approve:{slug}:{user_id}"
            self.children[1].custom_id = f"forms:deny:{slug}:{user_id}"

    @discord.ui.button(
        label="✅ Approve", style=discord.ButtonStyle.green, custom_id="forms:approve:_"
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_reviewer(interaction, self.config, self.slug):
            await interaction.response.send_message(
                "You don't have permission to review this application.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        assignments = await self.config.guild(guild).application_assignments()
        app_conf = assignments.get(self.slug, {})
        approval_role_id = app_conf.get("approval_role_id")

        removal_role_id = app_conf.get("removal_role_id")
        member = guild.get_member(self.user_id)
        if member:
            if approval_role_id:
                role = guild.get_role(approval_role_id)
                if role:
                    await member.add_roles(role, reason=f"Approved via Forms cog: {self.slug}")
            if removal_role_id:
                role = guild.get_role(removal_role_id)
                if role:
                    await member.remove_roles(role, reason=f"Approved via Forms cog: {self.slug}")

        try:
            user = member or await self.bot.fetch_user(self.user_id)
            await user.send(
                f"🎉 Congratulations! Your **{self.slug.replace('-', ' ').title()}** "
                "application has been **approved**!"
            )
        except discord.Forbidden:
            pass

        # Clear cooldown on approval
        if member:
            cooldowns = await self.config.user(member).application_cooldowns()
            cooldowns.pop(self.slug, None)
            await self.config.user(member).application_cooldowns.set(cooldowns)

        # Clean up
        assignments[self.slug]["active_reviews"].pop(str(self.user_id), None)
        await self.config.guild(guild).application_assignments.set(assignments)
        await interaction.channel.send(f"✅ **Approved** by {interaction.user.mention}")

        # Replace buttons with post-decision view
        post_view = PostReviewView(self.config, self.bot, self.slug, self.user_id, self.guild_id)
        await interaction.message.edit(view=post_view)

        await interaction.followup.send("✅ Application approved. User notified.", ephemeral=True)

    @discord.ui.button(
        label="❌ Deny", style=discord.ButtonStyle.red, custom_id="forms:deny:_"
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_reviewer(interaction, self.config, self.slug):
            await interaction.response.send_message(
                "You don't have permission to review this application.", ephemeral=True
            )
            return
        modal = DenyReasonModal(
            self.config, self.bot, self.slug, self.user_id,
            self.guild_id, interaction.channel,
            review_message_id=interaction.message.id,
        )
        await interaction.response.send_modal(modal)


class PostReviewView(discord.ui.View):
    """Persistent view shown after an application is approved or denied."""

    def __init__(self, config: Config, bot, slug: str, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.slug = slug
        self.user_id = user_id
        self.guild_id = guild_id
        if len(self.children) >= 2:
            self.children[0].custom_id = f"forms:reset_cooldown:{slug}:{user_id}"
            self.children[1].custom_id = f"forms:close_log:{slug}:{user_id}"

    @discord.ui.button(
        label="🔄 Reset Cooldown",
        style=discord.ButtonStyle.blurple,
        custom_id="forms:reset_cooldown:_",
    )
    async def reset_cooldown(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_reviewer(interaction, self.config, self.slug):
            await interaction.response.send_message(
                "You don't have permission to manage this application.", ephemeral=True
            )
            return
        guild = interaction.guild or self.bot.get_guild(self.guild_id)
        user = (guild.get_member(self.user_id) if guild else None) or await self.bot.fetch_user(self.user_id)
        cooldowns = await self.config.user(user).application_cooldowns()
        cooldowns.pop(self.slug, None)
        await self.config.user(user).application_cooldowns.set(cooldowns)
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(
            f"🔄 Cooldown cleared by {interaction.user.mention} — {user.mention} can re-apply immediately."
        )
        await interaction.followup.send("✅ Cooldown cleared.", ephemeral=True)

    @discord.ui.button(
        label="📁 Close Log",
        style=discord.ButtonStyle.grey,
        custom_id="forms:close_log:_",
    )
    async def close_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _check_reviewer(interaction, self.config, self.slug):
            await interaction.response.send_message(
                "You don't have permission to manage this application.", ephemeral=True
            )
            return
        await interaction.response.defer()
        await interaction.channel.edit(archived=True, locked=True)


class EditTicketCategoriesModal(discord.ui.Modal, title="Edit Ticket Categories"):
    categories = discord.ui.TextInput(
        label="Categories (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="Bug Report\nPayment Issue\nGeneral Question",
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cats = [c.strip() for c in self.categories.value.splitlines() if c.strip()]
        await interaction.client.cogs["Forms"].config.guild(interaction.guild).ticket_categories.set(cats)
        await interaction.response.send_message(
            f"✅ Categories updated: {', '.join(cats)}", ephemeral=True
        )


class MaxTicketsModal(discord.ui.Modal, title="Max Open Tickets"):
    value = discord.ui.TextInput(label="Max tickets per user", placeholder="3", max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(self.value.value)
            assert 1 <= n <= 20
        except (ValueError, AssertionError):
            await interaction.response.send_message(
                "Please enter a number between 1 and 20.", ephemeral=True
            )
            return
        await interaction.client.cogs["Forms"].config.guild(interaction.guild).ticket_max_open.set(n)
        await interaction.response.send_message(f"✅ Max open tickets set to {n}.", ephemeral=True)


class TicketSettingsView(discord.ui.View):
    def __init__(self, config: Config, bot):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot

    @discord.ui.button(label="Change Ticket Channel", style=discord.ButtonStyle.blurple)
    async def change_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WizardStep1View(self.config, interaction.guild.id, self.bot)
        await interaction.response.send_message(
            "Select the new ticket channel:", view=view, ephemeral=True
        )

    @discord.ui.button(label="Edit Categories", style=discord.ButtonStyle.grey)
    async def edit_categories(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditTicketCategoriesModal())

    @discord.ui.button(label="Set Max Tickets", style=discord.ButtonStyle.grey)
    async def set_max_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MaxTicketsModal())

    @discord.ui.button(label="Re-post Ticket Panel", style=discord.ButtonStyle.green)
    async def repost_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_id = await self.config.guild(interaction.guild).ticket_channel()
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            await interaction.response.send_message("Ticket channel not configured.", ephemeral=True)
            return
        manager = interaction.client.cogs["Forms"].tickets
        await manager.post_panel(channel)
        await interaction.response.send_message("✅ Ticket panel re-posted.", ephemeral=True)


class _SingleSelectView(discord.ui.View):
    def __init__(self, options, placeholder="Select…"):
        super().__init__(timeout=60)
        self.selected = None
        select = discord.ui.Select(options=options, placeholder=placeholder)
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction):
        self.selected = interaction.data["values"][0]
        await interaction.response.defer()
        self.stop()


class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.confirmed = False

    @discord.ui.button(label="Yes, delete", style=discord.ButtonStyle.red)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()


class _ChannelSelectStepView(discord.ui.View):
    """Single channel select step used during application assignment."""

    def __init__(self):
        super().__init__(timeout=120)
        self.selected_channel = None

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select a channel…",
        channel_types=[discord.ChannelType.text],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.selected_channel = select.values[0]
        await interaction.response.defer()
        self.stop()


class _RoleSelectStepView(discord.ui.View):
    """Single role select step used during application assignment."""

    def __init__(self):
        super().__init__(timeout=120)
        self.selected_role_id = None

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select approval role… (optional)",
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role_id = select.values[0].id if select.values else None
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Skip (no auto-role)", style=discord.ButtonStyle.grey)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()


class _RequiredRoleSelectStepView(discord.ui.View):
    """Single role select step for choosing a role applicants must already have."""

    def __init__(self):
        super().__init__(timeout=120)
        self.selected_role_id = None

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select required role… (optional)",
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role_id = select.values[0].id if select.values else None
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Skip (no requirement)", style=discord.ButtonStyle.grey)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()


class _RemoveRoleSelectStepView(discord.ui.View):
    """Single role select step for choosing a role to remove on approval."""

    def __init__(self):
        super().__init__(timeout=120)
        self.selected_role_id = None

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select role to remove… (optional)",
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role_id = select.values[0].id if select.values else None
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Skip (no role removal)", style=discord.ButtonStyle.grey)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()


class _ForumSelectStepView(discord.ui.View):
    """Single forum select step used during application assignment."""

    def __init__(self):
        super().__init__(timeout=120)
        self.selected_channel = None

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select review forum channel…",
        channel_types=[discord.ChannelType.forum],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.selected_channel = select.values[0]
        await interaction.response.defer()
        self.stop()


class _ReviewerRolesStepView(discord.ui.View):
    """Multi-role select for choosing reviewer roles on an application."""

    def __init__(self):
        super().__init__(timeout=120)
        self.selected_role_ids: list[int] = []

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select additional reviewer roles…",
        min_values=1,
        max_values=10,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role_ids = [r.id for r in select.values]
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Skip (staff only)", style=discord.ButtonStyle.grey)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()


class ApplicationSettingsView(discord.ui.View):
    def __init__(self, config: Config, bot):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot

    @discord.ui.button(label="➕ Create Application", style=discord.ButtonStyle.green)
    async def create_app(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CreateApplicationModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        from redbot.core.data_manager import cog_data_path
        from .applications import ApplicationManager
        manager = ApplicationManager(self.bot, self.config, cog_data_path(self.bot.cogs["Forms"]))
        try:
            await interaction.user.create_dm()
        except discord.Forbidden:
            await interaction.followup.send(
                "Please enable DMs to use the application builder.", ephemeral=True
            )
            return
        await manager.create_application(
            interaction.user, modal.result_name, modal.result_description
        )

    @discord.ui.button(label="✏️ Edit Application", style=discord.ButtonStyle.blurple)
    async def edit_app(self, interaction: discord.Interaction, button: discord.ui.Button):
        from redbot.core.data_manager import cog_data_path
        from .applications import ApplicationManager
        manager = ApplicationManager(self.bot, self.config, cog_data_path(self.bot.cogs["Forms"]))
        apps = await manager.load_applications()
        if not apps:
            await interaction.response.send_message("No applications saved yet.", ephemeral=True)
            return
        options = [discord.SelectOption(label=a["name"], value=slug) for slug, a in apps.items()]
        view = _SingleSelectView(options, placeholder="Select application to edit…")
        await interaction.response.send_message("Which application?", view=view, ephemeral=True)
        await view.wait()
        if view.selected:
            await manager.edit_application(interaction.user, view.selected)

    @discord.ui.button(label="🗑️ Delete Application", style=discord.ButtonStyle.red)
    async def delete_app(self, interaction: discord.Interaction, button: discord.ui.Button):
        from redbot.core.data_manager import cog_data_path
        from .applications import ApplicationManager
        manager = ApplicationManager(self.bot, self.config, cog_data_path(self.bot.cogs["Forms"]))
        apps = await manager.load_applications()
        if not apps:
            await interaction.response.send_message("No applications to delete.", ephemeral=True)
            return
        options = [discord.SelectOption(label=a["name"], value=slug) for slug, a in apps.items()]
        view = _SingleSelectView(options, placeholder="Select application to delete…")
        await interaction.response.send_message("Which application?", view=view, ephemeral=True)
        await view.wait()
        if view.selected:
            confirm = ConfirmView()
            await interaction.followup.send(
                f"Delete **{apps[view.selected]['name']}**? This cannot be undone.",
                view=confirm, ephemeral=True
            )
            await confirm.wait()
            if confirm.confirmed:
                await manager.delete_application(view.selected)
                assignments = await self.config.guild(interaction.guild).application_assignments()
                assignments.pop(view.selected, None)
                await self.config.guild(interaction.guild).application_assignments.set(assignments)
                await interaction.followup.send("✅ Application deleted.", ephemeral=True)

    @discord.ui.button(label="📊 Manage Assignments", style=discord.ButtonStyle.blurple)
    async def manage_assignments(self, interaction: discord.Interaction, button: discord.ui.Button):
        from redbot.core.data_manager import cog_data_path
        from .applications import ApplicationManager
        manager = ApplicationManager(self.bot, self.config, cog_data_path(self.bot.cogs["Forms"]))

        assignments = await self.config.guild(interaction.guild).application_assignments()
        if not assignments:
            await interaction.response.send_message(
                "No applications are currently assigned.", ephemeral=True
            )
            return

        apps = await manager.load_applications()
        options = [
            discord.SelectOption(label=apps.get(slug, {}).get("name", slug), value=slug)
            for slug in assignments
        ]
        view = _SingleSelectView(options, placeholder="Select an assigned application…")
        await interaction.response.send_message(
            "Which assignment do you want to manage?", view=view, ephemeral=True
        )
        await view.wait()
        if not view.selected:
            return

        slug = view.selected
        assignment = assignments[slug]
        app = apps.get(slug, {})

        embed = _build_assignment_embed(app, assignment, slug, interaction.guild)
        mgmt_view = _AssignmentManagementView(self.config, self.bot, slug, assignment)
        await interaction.followup.send(embed=embed, view=mgmt_view, ephemeral=True)

    @discord.ui.button(label="📌 Assign to Channel", style=discord.ButtonStyle.grey)
    async def assign_app(self, interaction: discord.Interaction, button: discord.ui.Button):
        from redbot.core.data_manager import cog_data_path
        from .applications import ApplicationManager
        manager = ApplicationManager(self.bot, self.config, cog_data_path(self.bot.cogs["Forms"]))
        apps = await manager.load_applications()
        if not apps:
            await interaction.response.send_message("No applications saved yet.", ephemeral=True)
            return
        options = [discord.SelectOption(label=a["name"], value=slug) for slug, a in apps.items()]
        view = _SingleSelectView(options, placeholder="Select application to assign…")
        await interaction.response.send_message(
            "**Step 1 of 7:** Which application do you want to assign to a channel?",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.selected:
            return
        slug = view.selected
        app = apps[slug]

        # Step 2: pick channel
        channel_view = _ChannelSelectStepView()
        await interaction.followup.send(
            f"**Step 2 of 7:** Select the channel where the **{app['name']}** Apply button will be posted.",
            view=channel_view,
            ephemeral=True,
        )
        await channel_view.wait()
        if not channel_view.selected_channel:
            return
        actual_channel = interaction.guild.get_channel(channel_view.selected_channel.id)
        if not actual_channel:
            await interaction.followup.send("Could not find the selected channel.", ephemeral=True)
            return

        # Step 3: pick review forum
        forum_view = _ForumSelectStepView()
        await interaction.followup.send(
            "**Step 3 of 7:** Select the **forum channel** where submitted applications will be posted for review.",
            view=forum_view,
            ephemeral=True,
        )
        await forum_view.wait()
        review_forum_id = forum_view.selected_channel.id if forum_view.selected_channel else None

        # Step 4: pick approval role
        role_view = _RoleSelectStepView()
        await interaction.followup.send(
            "**Step 4 of 7:** Select the role to **grant** on approval (or skip for none).",
            view=role_view,
            ephemeral=True,
        )
        await role_view.wait()

        # Step 5: pick removal role
        remove_role_view = _RemoveRoleSelectStepView()
        await interaction.followup.send(
            "**Step 5 of 7:** Select the role to **remove** on approval (or skip for none).",
            view=remove_role_view,
            ephemeral=True,
        )
        await remove_role_view.wait()

        # Step 6: pick required role
        required_role_view = _RequiredRoleSelectStepView()
        await interaction.followup.send(
            "**Step 6 of 7:** Select a role applicants **must already have** to apply (or skip for no requirement).",
            view=required_role_view,
            ephemeral=True,
        )
        await required_role_view.wait()

        # Step 7: pick reviewer roles
        reviewer_roles_view = _ReviewerRolesStepView()
        await interaction.followup.send(
            "**Step 7 of 7:** Select **additional roles** that can approve/deny/manage this application "
            "(staff can always review — skip to keep it staff-only).",
            view=reviewer_roles_view,
            ephemeral=True,
        )
        await reviewer_roles_view.wait()

        await manager.assign_application(
            guild=interaction.guild,
            slug=slug,
            name=app["name"],
            description=app["description"],
            channel=actual_channel,
            approval_role_id=role_view.selected_role_id,
            removal_role_id=remove_role_view.selected_role_id,
            required_role_id=required_role_view.selected_role_id,
            review_forum_id=review_forum_id,
            reviewer_role_ids=reviewer_roles_view.selected_role_ids,
        )
        await interaction.followup.send(
            f"✅ **{app['name']}** has been assigned to {actual_channel.mention}!",
            ephemeral=True,
        )


def _build_assignment_embed(app: dict, assignment: dict, slug: str, guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title=f"Assignment: {app.get('name', slug)}",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Channel", value=f"<#{assignment['channel_id']}>", inline=True)

    forum_id = assignment.get("review_forum_id")
    embed.add_field(name="Review Forum", value=f"<#{forum_id}>" if forum_id else "Not set", inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    approval_id = assignment.get("approval_role_id")
    embed.add_field(name="Approval Role", value=f"<@&{approval_id}>" if approval_id else "None", inline=True)

    removal_id = assignment.get("removal_role_id")
    embed.add_field(name="Removal Role", value=f"<@&{removal_id}>" if removal_id else "None", inline=True)

    required_id = assignment.get("required_role_id")
    embed.add_field(name="Required Role", value=f"<@&{required_id}>" if required_id else "None", inline=True)

    reviewer_ids = assignment.get("reviewer_role_ids", [])
    reviewer_text = " ".join(f"<@&{rid}>" for rid in reviewer_ids) if reviewer_ids else "Staff only"
    embed.add_field(name="Additional Reviewer Roles", value=reviewer_text, inline=False)

    active = len(assignment.get("active_reviews", {}))
    embed.set_footer(text=f"{active} active review(s)")
    return embed


class _AssignmentManagementView(discord.ui.View):
    def __init__(self, config: Config, bot, slug: str, assignment: dict):
        super().__init__(timeout=120)
        self.config = config
        self.bot = bot
        self.slug = slug
        self.assignment = assignment

    @discord.ui.button(label="✏️ Edit Assignment", style=discord.ButtonStyle.blurple)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        forum_view = _ForumSelectStepView()
        current_forum_id = self.assignment.get("review_forum_id")
        forum_hint = f" (currently <#{current_forum_id}>)" if current_forum_id else ""
        await interaction.followup.send(
            f"**Edit Step 1 of 5:** Select the review forum{forum_hint}.",
            view=forum_view, ephemeral=True,
        )
        await forum_view.wait()

        role_view = _RoleSelectStepView()
        current_approval = self.assignment.get("approval_role_id")
        approval_hint = f" (currently <@&{current_approval}>)" if current_approval else ""
        await interaction.followup.send(
            f"**Edit Step 2 of 5:** Select the approval role{approval_hint} (or skip for none).",
            view=role_view, ephemeral=True,
        )
        await role_view.wait()

        remove_view = _RemoveRoleSelectStepView()
        current_removal = self.assignment.get("removal_role_id")
        removal_hint = f" (currently <@&{current_removal}>)" if current_removal else ""
        await interaction.followup.send(
            f"**Edit Step 3 of 5:** Select the removal role{removal_hint} (or skip for none).",
            view=remove_view, ephemeral=True,
        )
        await remove_view.wait()

        required_view = _RequiredRoleSelectStepView()
        current_required = self.assignment.get("required_role_id")
        required_hint = f" (currently <@&{current_required}>)" if current_required else ""
        await interaction.followup.send(
            f"**Edit Step 4 of 5:** Select the required role{required_hint} (or skip for none).",
            view=required_view, ephemeral=True,
        )
        await required_view.wait()

        reviewer_view = _ReviewerRolesStepView()
        current_reviewers = self.assignment.get("reviewer_role_ids", [])
        reviewer_hint = (
            " (currently " + ", ".join(f"<@&{r}>" for r in current_reviewers) + ")"
            if current_reviewers else " (currently staff only)"
        )
        await interaction.followup.send(
            f"**Edit Step 5 of 5:** Select additional reviewer roles{reviewer_hint} (or skip for staff only).",
            view=reviewer_view, ephemeral=True,
        )
        await reviewer_view.wait()

        guild_conf = self.config.guild(interaction.guild)
        assignments = await guild_conf.application_assignments()
        if self.slug not in assignments:
            await interaction.followup.send("Assignment no longer exists.", ephemeral=True)
            return

        if forum_view.selected_channel:
            assignments[self.slug]["review_forum_id"] = forum_view.selected_channel.id
        assignments[self.slug]["approval_role_id"] = role_view.selected_role_id
        assignments[self.slug]["removal_role_id"] = remove_view.selected_role_id
        assignments[self.slug]["required_role_id"] = required_view.selected_role_id
        assignments[self.slug]["reviewer_role_ids"] = reviewer_view.selected_role_ids

        await guild_conf.application_assignments.set(assignments)
        await interaction.followup.send("✅ Assignment updated.", ephemeral=True)

    @discord.ui.button(label="🗑️ Remove Assignment", style=discord.ButtonStyle.red)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        confirm = ConfirmView()
        app_name = self.assignment.get("name", self.slug)
        await interaction.response.send_message(
            f"Remove the **{self.slug}** assignment? The Apply button message will be deleted from the channel.",
            view=confirm, ephemeral=True,
        )
        await confirm.wait()
        if not confirm.confirmed:
            await interaction.followup.send("Cancelled.", ephemeral=True)
            return

        guild = interaction.guild
        channel_id = self.assignment.get("channel_id")
        panel_msg_id = self.assignment.get("panel_message_id")
        if channel_id and panel_msg_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(panel_msg_id)
                    await msg.delete()
                except Exception:
                    pass

        assignments = await self.config.guild(guild).application_assignments()
        assignments.pop(self.slug, None)
        await self.config.guild(guild).application_assignments.set(assignments)
        await interaction.followup.send("✅ Assignment removed.", ephemeral=True)


class SettingsPanelView(discord.ui.View):
    def __init__(self, config: Config, bot):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot

    @discord.ui.button(label="🎫 Ticket Settings", style=discord.ButtonStyle.blurple)
    async def ticket_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TicketSettingsView(self.config, self.bot)
        embed = discord.Embed(title="🎫 Ticket Settings", color=discord.Color.blurple())
        guild_conf = self.config.guild(interaction.guild)
        channel_id = await guild_conf.ticket_channel()
        embed.add_field(
            name="Ticket Channel",
            value=f"<#{channel_id}>" if channel_id else "Not set"
        )
        staff_role_id = await guild_conf.ticket_staff_role()
        embed.add_field(
            name="Staff Role",
            value=f"<@&{staff_role_id}>" if staff_role_id else "Not set"
        )
        categories = await guild_conf.ticket_categories()
        embed.add_field(
            name="Categories",
            value=", ".join(categories) or "None",
            inline=False
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="📋 Application Settings", style=discord.ButtonStyle.green)
    async def application_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ApplicationSettingsView(self.config, self.bot)
        embed = discord.Embed(title="📋 Application Settings", color=discord.Color.green())
        from redbot.core.data_manager import cog_data_path
        from .applications import ApplicationManager
        manager = ApplicationManager(self.bot, self.config, cog_data_path(self.bot.cogs["Forms"]))
        apps = await manager.load_applications()
        if apps:
            embed.add_field(
                name="Saved Applications",
                value="\n".join(f"• {a['name']} (`{slug}`)" for slug, a in apps.items()),
                inline=False,
            )
        else:
            embed.add_field(name="Saved Applications", value="None yet", inline=False)

        assignments = await self.config.guild(interaction.guild).application_assignments()
        if assignments:
            lines = []
            for slug, asgn in assignments.items():
                app_name = apps.get(slug, {}).get("name", slug)
                channel_id = asgn.get("channel_id")
                lines.append(f"• **{app_name}** → <#{channel_id}>")
            embed.add_field(name="Assigned Applications", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Assigned Applications", value="None", inline=False)

        await interaction.response.edit_message(embed=embed, view=view)
