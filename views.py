"""All Discord UI views and modals for the Filecab cog."""
from __future__ import annotations
import discord
from redbot.core import Config
from .utils import can_review


def build_template_options(cog) -> list[discord.SelectOption]:
    """Build select options from the cog's currently loaded templates."""
    return [
        discord.SelectOption(label=spec.get("name", slug), value=slug)
        for slug, spec in cog.templates.all_templates().items()
    ][:25]


async def post_document_panel(guild: discord.Guild, config: Config, bot) -> discord.Message | None:
    """Post (or re-post) the document-type select panel to the configured channel."""
    cog = bot.cogs["Filecab"]
    options = build_template_options(cog)
    if not options:
        return None

    channel_id = await config.guild(guild).document_channel()
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return None

    embed = discord.Embed(
        title="📁 File a Document",
        description="Select a document type below to begin filing it.",
        color=discord.Color.blurple(),
    )
    view = TemplateSelectView(config, bot, options)
    msg = await channel.send(embed=embed, view=view)
    await config.guild(guild).panel_message_id.set(msg.id)
    return msg


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------

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
    """Step 1: select the document channel."""

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select the document channel…",
        channel_types=[discord.ChannelType.text],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("⚠️ Please select a channel first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).document_channel.set(self._selected.id)
        self.stop()
        view = WizardStep2View(self.config, self.guild_id, self.bot)
        embed = discord.Embed(
            title="Filecab Setup — Step 2 of 3",
            description="Select the **staff review forum** where pending filings are posted for Approve/Deny.",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep2View(_WizardStepView):
    """Step 2: select the staff review forum."""

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select the review forum…",
        channel_types=[discord.ChannelType.forum],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("⚠️ Please select a forum first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).document_review_forum.set(self._selected.id)
        self.stop()
        view = WizardStep3View(self.config, self.guild_id, self.bot)
        embed = discord.Embed(
            title="Filecab Setup — Step 3 of 3",
            description=(
                "Optionally select an **approval role** (admins can always approve/deny).\n"
                "Use the toggle to control whether filings need staff approval before publishing."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep3View(_WizardStepView):
    """Step 3: approval role + require-approval toggle, then finish."""

    def __init__(self, config: Config, guild_id: int, bot):
        super().__init__(config, guild_id, bot)
        self._approval_required = True

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select an approval role (optional)…",
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Approval Required: ON", style=discord.ButtonStyle.blurple)
    async def toggle_approval(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._approval_required = not self._approval_required
        button.label = f"Approval Required: {'ON' if self._approval_required else 'OFF'}"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Finish Setup", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_conf = self.config.guild_from_id(self.guild_id)
        await guild_conf.approval_role.set(self._selected.id if self._selected else None)
        await guild_conf.approval_required.set(self._approval_required)
        self.stop()
        await interaction.response.defer(ephemeral=True)

        guild = self.bot.get_guild(self.guild_id)
        msg = await post_document_panel(guild, self.config, self.bot) if guild else None
        if msg:
            await interaction.followup.send(
                "✅ Setup complete! The document panel has been posted.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "✅ Setup saved, but no templates are loaded yet (or the document channel "
                "couldn't be found), so the panel wasn't posted. Drop template HTML+JSON "
                "pairs into the cog's data folder, then use `filecab settings` → "
                "**Repost Panel**.",
                ephemeral=True,
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


# ---------------------------------------------------------------------------
# Document panel (persistent)
# ---------------------------------------------------------------------------

class TemplateSelectView(discord.ui.View):
    """Persistent view: document-type select posted in the document channel."""

    def __init__(self, config: Config, bot, options: list[discord.SelectOption]):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.add_item(self._TemplateSelect(options))

    class _TemplateSelect(discord.ui.Select):
        def __init__(self, options: list[discord.SelectOption]):
            super().__init__(
                placeholder="Select a document type to file…",
                options=options,
                custom_id="filecab:template_select",
            )

        async def callback(self, interaction: discord.Interaction):
            slug = self.values[0]
            cog = interaction.client.cogs["Filecab"]
            try:
                dm = await interaction.user.create_dm()
            except discord.Forbidden:
                await interaction.response.send_message(
                    "⚠️ I couldn't DM you. Please enable DMs from server members and try again.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                "📬 Check your DMs — I've sent you the first question!", ephemeral=True
            )
            await cog.filing.start_filing(interaction.user, interaction.guild, slug, dm)


# ---------------------------------------------------------------------------
# Review forum (persistent)
# ---------------------------------------------------------------------------

class FilingReviewView(discord.ui.View):
    """Persistent Approve/Deny buttons for a pending document filing."""

    def __init__(self, config: Config, bot, doc_id: str):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.doc_id = doc_id
        if len(self.children) >= 2:
            self.children[0].custom_id = f"filecab:approve:{doc_id}"
            self.children[1].custom_id = f"filecab:deny:{doc_id}"

    async def _can_review(self, interaction: discord.Interaction) -> bool:
        role_id = await self.config.guild(interaction.guild).approval_role()
        return await can_review(interaction, role_id)

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.green, custom_id="filecab:approve:_")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._can_review(interaction):
            await interaction.response.send_message(
                "⚠️ You don't have permission to review filings.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.cogs["Filecab"]
        await cog.filing.approve(interaction.guild, self.doc_id)
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send("✅ Approved and published.", ephemeral=True)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.red, custom_id="filecab:deny:_")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._can_review(interaction):
            await interaction.response.send_message(
                "⚠️ You don't have permission to review filings.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.cogs["Filecab"]
        await cog.filing.deny(interaction.guild, self.doc_id)
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send("❌ Denied.", ephemeral=True)


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

class SettingsPanelView(discord.ui.View):
    def __init__(self, config: Config, bot):
        super().__init__(timeout=180)
        self.config = config
        self.bot = bot

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Change document channel…",
        channel_types=[discord.ChannelType.text],
        row=0,
    )
    async def change_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await self.config.guild(interaction.guild).document_channel.set(select.values[0].id)
        await interaction.response.send_message(
            f"✅ Document channel set to {select.values[0].mention}.", ephemeral=True
        )

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Change review forum…",
        channel_types=[discord.ChannelType.forum],
        row=1,
    )
    async def change_forum(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await self.config.guild(interaction.guild).document_review_forum.set(select.values[0].id)
        await interaction.response.send_message(
            f"✅ Review forum set to {select.values[0].mention}.", ephemeral=True
        )

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Change approval role…",
        row=2,
    )
    async def change_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        await self.config.guild(interaction.guild).approval_role.set(select.values[0].id)
        await interaction.response.send_message(
            f"✅ Approval role set to {select.values[0].mention}.", ephemeral=True
        )

    @discord.ui.button(label="Toggle Require Approval", style=discord.ButtonStyle.blurple, row=3)
    async def toggle_approval(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_conf = self.config.guild(interaction.guild)
        current = await guild_conf.approval_required()
        await guild_conf.approval_required.set(not current)
        await interaction.response.send_message(
            f"✅ Approval required is now **{'ON' if not current else 'OFF'}**.", ephemeral=True
        )

    @discord.ui.button(label="Reload Templates", style=discord.ButtonStyle.blurple, row=3)
    async def reload_templates(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        templates = cog.templates.reload()
        if templates:
            listing = "\n".join(f"• {spec.get('name', slug)} (`{slug}`)" for slug, spec in templates.items())
        else:
            listing = "None found."
        await interaction.response.send_message(
            f"🔄 Reloaded. **{len(templates)}** template(s) loaded:\n{listing}", ephemeral=True
        )

    @discord.ui.button(label="Repost Panel", style=discord.ButtonStyle.blurple, row=3)
    async def repost_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = await post_document_panel(interaction.guild, self.config, self.bot)
        if msg:
            await interaction.response.send_message("✅ Document panel re-posted.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "⚠️ Couldn't post the panel — check that templates are loaded and the "
                "document channel is set.",
                ephemeral=True,
            )

    @discord.ui.button(label="Manage Documents", style=discord.ButtonStyle.grey, row=4)
    async def manage_documents(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_conf = self.config.guild(interaction.guild)
        published = await guild_conf.published_documents()
        live = {k: v for k, v in published.items() if v.get("status") == "published"}
        if not live:
            await interaction.response.send_message("No published documents to manage.", ephemeral=True)
            return
        view = ManageDocumentsView(self.config, self.bot, live)
        await interaction.response.send_message(
            "Select a document to take down:", view=view, ephemeral=True
        )


class ManageDocumentsView(discord.ui.View):
    """Ephemeral view for taking down a previously published document."""

    def __init__(self, config: Config, bot, documents: dict[str, dict]):
        super().__init__(timeout=120)
        self.config = config
        self.bot = bot
        options = [
            discord.SelectOption(label=f"{rec['slug']} ({doc_id})", value=doc_id)
            for doc_id, rec in list(documents.items())[:25]
        ]
        self.add_item(self._DocumentSelect(options))

    class _DocumentSelect(discord.ui.Select):
        def __init__(self, options: list[discord.SelectOption]):
            super().__init__(placeholder="Select a document…", options=options)

        async def callback(self, interaction: discord.Interaction):
            doc_id = self.values[0]
            cog = interaction.client.cogs["Filecab"]
            removed = await cog.filing.takedown(interaction.guild, doc_id)
            if removed:
                await interaction.response.edit_message(
                    content=f"🗑️ Took down `{doc_id}`.", view=None
                )
            else:
                await interaction.response.edit_message(
                    content=f"⚠️ Could not find `{doc_id}`.", view=None
                )
