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
        await _send_wizard_step6(interaction, self.config, self.guild_id, self.bot, self._selected)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class TicketCategoriesModal(discord.ui.Modal, title="Ticket Categories"):
    """Modal for entering ticket category names (up to 5)."""

    cat1 = discord.ui.TextInput(label="Category 1", placeholder="e.g. General Support", required=True)
    cat2 = discord.ui.TextInput(label="Category 2", placeholder="e.g. Bug Report", required=False)
    cat3 = discord.ui.TextInput(label="Category 3", placeholder="e.g. Billing", required=False)
    cat4 = discord.ui.TextInput(label="Category 4", placeholder="Optional", required=False)
    cat5 = discord.ui.TextInput(label="Category 5", placeholder="Optional", required=False)
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
        categories = [
            v.strip()
            for v in [
                self.cat1.value,
                self.cat2.value,
                self.cat3.value,
                self.cat4.value,
                self.cat5.value,
            ]
            if v.strip()
        ]
        max_open = max(1, int(self.max_open.value)) if self.max_open.value.strip().isdigit() else 3
        await self.config.guild_from_id(self.guild_id).ticket_categories.set(categories)
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
