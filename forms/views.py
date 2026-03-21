"""All Discord UI views, modals, and components for the Forms cog."""
from __future__ import annotations
import discord
from redbot.core import Config
from .utils import check_staff_role


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
        await _send_wizard_step3(interaction, self.config, self.guild_id, self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep3View(_WizardStepView):
    """Step 3: Select ticket user role."""

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select the ticket user role…",
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("Please select a role first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).ticket_user_role.set(self._selected.id)
        self.stop()
        await _send_wizard_step4(interaction, self.config, self.guild_id, self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep4View(_WizardStepView):
    """Step 4: Select ticket staff role."""

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
    """Step 5: Select staff forum channel."""

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
        # Resolve AppCommandChannel to a full ForumChannel object
        forum = interaction.guild.get_channel(self._selected.id)
        if not isinstance(forum, discord.ForumChannel):
            await interaction.response.edit_message(
                content="⚠️ Could not resolve the selected forum channel. Please try again.",
                view=None,
                embed=None,
            )
            return
        await _send_wizard_step6(interaction, self.config, self.guild_id, self.bot, forum)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class TicketCategoriesModal(discord.ui.Modal, title="Ticket Categories"):
    """Modal for entering ticket category names and max-open limit."""

    categories = discord.ui.TextInput(
        label="Categories (one per line, up to 5)",
        style=discord.TextStyle.paragraph,
        placeholder="General Support\nBug Report\nBilling",
        required=True,
    )
    max_open = discord.ui.TextInput(
        label="Max open tickets per user",
        placeholder="3",
        required=False,
        max_length=2,
    )

    def __init__(self, config: Config, guild_id: int, bot):
        super().__init__()
        self.config = config
        self.guild_id = guild_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        cats = [line.strip() for line in self.categories.value.splitlines() if line.strip()][:5]
        max_open = max(1, int(self.max_open.value)) if self.max_open.value.strip().isdigit() else 3
        await self.config.guild_from_id(self.guild_id).ticket_categories.set(cats)
        await self.config.guild_from_id(self.guild_id).ticket_max_open.set(max_open)
        await finish_wizard(interaction, self.config, self.guild_id, self.bot)


class WizardStep7View(_WizardStepView):
    """Step 7: Enter ticket categories via modal."""

    @discord.ui.button(label="Enter Categories", style=discord.ButtonStyle.blurple)
    async def enter_categories(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        modal = TicketCategoriesModal(self.config, self.guild_id, self.bot)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


async def _ensure_forum_tags(forum: discord.ForumChannel, config: Config, guild_id: int) -> None:
    """Create TICKET and APPLICATION tags if they don't exist; store IDs in config."""
    existing = {t.name: t for t in forum.available_tags}
    ticket_tag = existing.get("TICKET") or await forum.create_tag(name="TICKET")
    app_tag = existing.get("APPLICATION") or await forum.create_tag(name="APPLICATION")
    await config.guild_from_id(guild_id).ticket_tag_id.set(ticket_tag.id)
    await config.guild_from_id(guild_id).application_tag_id.set(app_tag.id)


async def _send_wizard_step2(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep2View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 2 of 7",
        description="Select the **category** where ticket channels will be created.",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def _send_wizard_step3(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep3View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 3 of 7",
        description="Select the **ticket user role** that members need to open tickets.",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def _send_wizard_step4(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep4View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 4 of 7",
        description="Select the **staff role** that can manage and close tickets.",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def _send_wizard_step5(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep5View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 5 of 7",
        description="Select the **forum channel** where ticket and application transcripts will be archived.",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(embed=embed, view=view)


async def _send_wizard_step6(
    interaction: discord.Interaction, config: Config, guild_id: int, bot, forum: discord.ForumChannel
) -> None:
    await _ensure_forum_tags(forum, config, guild_id)
    embed = discord.Embed(
        title="Forms Setup — Step 6 of 7",
        description="✅ Forum tags created: **TICKET** and **APPLICATION**.\n\nClick **Next** to set up ticket categories.",
        color=discord.Color.green(),
    )
    view = _Step6NextView(config, guild_id, bot)
    await interaction.response.edit_message(embed=embed, view=view)


class _Step6NextView(_WizardStepView):
    """Step 6 confirmation — just a Next button."""

    @discord.ui.button(label="Next", style=discord.ButtonStyle.green)
    async def next_step(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await _send_wizard_step7(interaction, self.config, self.guild_id, self.bot)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


async def _send_wizard_step7(interaction: discord.Interaction, config: Config, guild_id: int, bot) -> None:
    view = WizardStep7View(config, guild_id, bot)
    embed = discord.Embed(
        title="Forms Setup — Step 7 of 7",
        description=(
            "Click **Enter Categories** to open a form where you can name up to 5 ticket categories "
            "and set the max open tickets per user (default: 3)."
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

        # Role gate
        user_role_id = await guild_conf.ticket_user_role()
        if user_role_id and not any(r.id == user_role_id for r in interaction.user.roles):
            await interaction.response.send_message(
                "You don't have permission to open tickets.", ephemeral=True
            )
            return

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

    def __init__(self, config, bot, slug, user_id, guild_id, thread):
        super().__init__()
        self.config = config
        self.bot = bot
        self.slug = slug
        self.user_id = user_id
        self.guild_id = guild_id
        self.thread = thread

    async def on_submit(self, interaction: discord.Interaction):
        import time
        guild = interaction.guild
        user = guild.get_member(self.user_id) or await self.bot.fetch_user(self.user_id)

        # DM the denial reason
        try:
            assignments = await self.config.guild(guild).application_assignments()
            app_conf = assignments.get(self.slug, {})
            cooldown_days = app_conf.get("cooldown_days", 7)
            await user.send(
                f"Your **{self.slug.replace('-', ' ').title()}** application was not approved.\n\n"
                f"**Reason:** {self.reason.value}"
            )
        except discord.Forbidden:
            pass

        # Set cooldown
        expiry = time.time() + cooldown_days * 86400
        cooldowns = await self.config.user(user).application_cooldowns()
        cooldowns[self.slug] = expiry
        await self.config.user(user).application_cooldowns.set(cooldowns)

        # Clean up active_reviews
        assignments = await self.config.guild(guild).application_assignments()
        if self.slug in assignments:
            assignments[self.slug]["active_reviews"].pop(str(self.user_id), None)
            await self.config.guild(guild).application_assignments.set(assignments)

        # Close forum thread
        await self.thread.edit(archived=True, locked=True)
        await interaction.response.send_message(
            "❌ Application denied. User has been notified.", ephemeral=True
        )


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
        guild = interaction.guild
        assignments = await self.config.guild(guild).application_assignments()
        app_conf = assignments.get(self.slug, {})
        approval_role_id = app_conf.get("approval_role_id")

        member = guild.get_member(self.user_id)
        if member and approval_role_id:
            role = guild.get_role(approval_role_id)
            if role:
                await member.add_roles(role, reason=f"Approved via Forms cog: {self.slug}")

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
        await interaction.channel.edit(archived=True, locked=True)
        await interaction.response.send_message(
            "✅ Application approved. User notified.", ephemeral=True
        )

    @discord.ui.button(
        label="❌ Deny", style=discord.ButtonStyle.red, custom_id="forms:deny:_"
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = DenyReasonModal(
            self.config, self.bot, self.slug, self.user_id,
            self.guild_id, interaction.channel
        )
        await interaction.response.send_modal(modal)


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
        super().__init__(timeout=180)
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


class _CooldownModal(discord.ui.Modal, title="Re-application Cooldown"):
    days = discord.ui.TextInput(
        label="Cooldown (days)",
        placeholder="7",
        max_length=3,
        required=False,
    )

    def __init__(self):
        super().__init__()
        self.cooldown_days = 7

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(self.days.value or "7")
            self.cooldown_days = max(0, n)
        except ValueError:
            self.cooldown_days = 7
        await interaction.response.defer()
        self.stop()


class _OpenModalView(discord.ui.View):
    """One-button view that opens a modal when clicked."""

    def __init__(self, modal: discord.ui.Modal):
        super().__init__(timeout=120)
        self._modal = modal

    @discord.ui.button(label="Set Cooldown", style=discord.ButtonStyle.blurple)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.send_modal(self._modal)


class ApplicationSettingsView(discord.ui.View):
    def __init__(self, config: Config, bot):
        super().__init__(timeout=180)
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
            "**Step 1 of 3:** Which application do you want to assign to a channel?",
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
            f"**Step 2 of 3:** Select the channel where the **{app['name']}** Apply button will be posted.",
            view=channel_view,
            ephemeral=True,
        )
        await channel_view.wait()
        if not channel_view.selected_channel:
            return

        # Step 3: pick approval role
        role_view = _RoleSelectStepView()
        await interaction.followup.send(
            "**Step 3 of 3:** Select the role to grant on approval (or skip to set no auto-role).",
            view=role_view,
            ephemeral=True,
        )
        await role_view.wait()

        # Cooldown modal
        cooldown_modal = _CooldownModal()
        await interaction.followup.send(
            "Almost done! Click below to set the re-application cooldown.",
            view=_OpenModalView(cooldown_modal),
            ephemeral=True,
        )
        await cooldown_modal.wait()

        approval_role_id = role_view.selected_role_id
        cooldown_days = cooldown_modal.cooldown_days

        await manager.assign_application(
            guild=interaction.guild,
            slug=slug,
            name=app["name"],
            description=app["description"],
            channel=channel_view.selected_channel,
            approval_role_id=approval_role_id,
            cooldown_days=cooldown_days,
        )
        await interaction.followup.send(
            f"✅ **{app['name']}** has been assigned to {channel_view.selected_channel.mention}!",
            ephemeral=True,
        )


class SettingsPanelView(discord.ui.View):
    def __init__(self, config: Config, bot):
        super().__init__(timeout=180)
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
            embed.add_field(name="Saved Applications", value="None yet")
        await interaction.response.edit_message(embed=embed, view=view)
