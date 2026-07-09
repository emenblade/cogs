"""All Discord UI views and modals for the Filecab cog."""
from __future__ import annotations
from typing import Awaitable, Callable
import discord
from redbot.core import Config
from .template_manager import TemplateManager
from .utils import can_file_template, can_review, normalize_base_url


def build_template_options(cog, include_staff_authored: bool = False) -> list[discord.SelectOption]:
    """Build select options from the cog's currently loaded templates."""
    templates = cog.templates
    return [
        discord.SelectOption(label=spec["title"], value=template_id)
        for template_id, spec in templates.all_templates().items()
        if include_staff_authored or not templates.is_staff_authored(spec)
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
        self.message: discord.Message | None = None

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(
                    content="⏱️ Setup timed out — run `filecab setup` again to restart.",
                    embed=None, view=None,
                )
            except discord.HTTPException:
                pass


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
        view.message = interaction.message
        embed = discord.Embed(
            title="Filecab Setup — Step 2 of 4",
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
        view.message = interaction.message
        embed = discord.Embed(
            title="Filecab Setup — Step 3 of 4",
            description=(
                "Optionally select an **approval role** that can approve/deny filings "
                "and make them public (admins can always do both)."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep3View(_WizardStepView):
    """Step 3: approval role, then on to the site repository step."""

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select an approval role (optional)…",
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_conf = self.config.guild_from_id(self.guild_id)
        await guild_conf.approval_role.set(self._selected.id if self._selected else None)
        self.stop()
        view = WizardStep4View(self.config, self.guild_id, self.bot)
        view.message = interaction.message
        embed = discord.Embed(
            title="Filecab Setup — Step 4 of 4",
            description=(
                "Set the **site repository** — the GitHub repo (`owner/repo`) that serves as "
                "both the templates source and the publish destination, matching the structure "
                "the site already uses.\n\n"
                "Publishing also needs a GitHub token — run `[p]set api github token,<token>` "
                "separately (bot owner only); it isn't asked for here."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class SiteRepoModal(discord.ui.Modal, title="Site Repository"):
    """Collects the GitHub repo used for both fetching templates and publishing filings."""

    repo = discord.ui.TextInput(
        label="GitHub repo (owner/repo)",
        placeholder="emenblade/lcrpfilecab",
        max_length=100,
    )
    branch = discord.ui.TextInput(
        label="Branch",
        default="main",
        required=False,
        max_length=100,
    )
    base_url = discord.ui.TextInput(
        label="Site base URL (optional override)",
        placeholder="Leave blank for https://<owner>.github.io/<repo>",
        required=False,
        max_length=200,
    )

    def __init__(self, config: Config, on_done: Callable[[discord.Interaction, str, int, str], Awaitable[None]] | None = None):
        super().__init__()
        self.config = config
        self.on_done = on_done

    async def on_submit(self, interaction: discord.Interaction):
        repo_value = self.repo.value.strip()
        if "/" not in repo_value:
            await interaction.response.send_message(
                "⚠️ Repo must be in `owner/repo` format.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        branch = self.branch.value.strip() or "main"
        await self.config.site_repo.set(repo_value)
        await self.config.site_branch.set(branch)
        base_url_value = self.base_url.value.strip()
        await self.config.site_base_url.set(normalize_base_url(base_url_value) if base_url_value else None)

        cog = interaction.client.cogs["Filecab"]
        owner, repo = repo_value.split("/", 1)
        count = await cog.templates.refresh_from_repo(cog.github, owner, repo, branch)

        token = await cog.github.get_token()
        token_note = (
            "" if token else
            "\n⚠️ No GitHub token is set yet — publishing won't work until you run "
            "`[p]set api github token,<token>`."
        )

        if self.on_done:
            await self.on_done(interaction, repo_value, count, token_note)
        else:
            await interaction.followup.send(
                f"✅ Site repo set to `{repo_value}`. Fetched **{count}** template(s).{token_note}",
                ephemeral=True,
            )


class WizardStep4View(_WizardStepView):
    """Step 4: site repository, then finish."""

    @discord.ui.button(label="Set Site Repository", style=discord.ButtonStyle.blurple)
    async def set_repo(self, interaction: discord.Interaction, button: discord.ui.Button):
        origin_message = interaction.message

        async def _on_done(modal_interaction: discord.Interaction, repo_value: str, count: int, token_note: str):
            await self._finish(modal_interaction, origin_message, repo_value, count, token_note)

        await interaction.response.send_modal(SiteRepoModal(self.config, on_done=_on_done))

    @discord.ui.button(label="Skip for now", style=discord.ButtonStyle.grey)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self._finish(interaction, interaction.message, None, 0, "")

    async def _finish(
        self,
        interaction: discord.Interaction,
        origin_message: discord.Message | None,
        repo_value: str | None,
        count: int,
        token_note: str,
    ) -> None:
        self.stop()
        if origin_message is not None:
            try:
                await origin_message.edit(view=None)
            except discord.HTTPException:
                pass
        guild = self.bot.get_guild(self.guild_id)
        msg = await post_document_panel(guild, self.config, self.bot) if guild else None

        parts = []
        if repo_value:
            parts.append(f"✅ Site repo set to `{repo_value}`. Fetched **{count}** template(s).{token_note}")
        else:
            parts.append("Site repo not configured — set it later via `filecab settings`.")
        if msg:
            parts.append("✅ Setup complete! The document panel has been posted.")
        else:
            parts.append(
                "✅ Setup saved, but no citizen-facing templates are loaded yet (or the document "
                "channel couldn't be found), so the panel wasn't posted. Run `filecab refresh` "
                "once templates are available, then `filecab settings` → **Repost Panel**."
            )
        await interaction.followup.send("\n".join(parts), ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


# ---------------------------------------------------------------------------
# Document panel (persistent) + staff "file on behalf" command
# ---------------------------------------------------------------------------

class _ExpiringView(discord.ui.View):
    """Base for short-lived ephemeral/staff views.

    Removes its own buttons on timeout instead of leaving stale ones sitting
    there — clicking an expired component otherwise fails with a generic
    "This interaction failed" error, which is confusing. Callers must set
    `.message` right after sending (there's no way to get it otherwise).
    """

    def __init__(self, *, timeout: float):
        super().__init__(timeout=timeout)
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class TemplateSelectView(discord.ui.View):
    """Persistent view: document-type select posted in the document channel.

    Only lists templates a citizen can file (excludes judge-authored ones).
    """

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
            await _start_filing_from_select(interaction, self.values[0])


class StaffFileSelectView(_ExpiringView):
    """Ephemeral view for `filecab file`: staff can file any template, including
    judge-authored ones with no citizen applicant role. Access gates don't apply
    here — `filecab file` is already staff/admin-only."""

    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(timeout=120)
        self.add_item(self._TemplateSelect(options))

    class _TemplateSelect(discord.ui.Select):
        def __init__(self, options: list[discord.SelectOption]):
            super().__init__(placeholder="Select a document type to file…", options=options)

        async def callback(self, interaction: discord.Interaction):
            await _start_filing_from_select(interaction, self.values[0], enforce_gate=False)


async def _start_filing_from_select(
    interaction: discord.Interaction, template_id: str, *, enforce_gate: bool = True
) -> None:
    cog = interaction.client.cogs["Filecab"]
    if enforce_gate:
        access = await cog.config.guild(interaction.guild).template_access()
        allowed_role_ids = access.get(template_id, [])
        if allowed_role_ids and not await can_file_template(interaction, allowed_role_ids):
            spec = cog.templates.get(template_id)
            title = spec["title"] if spec else "this document"
            await interaction.response.send_message(
                f"⚠️ You don't have permission to file **{title}**.", ephemeral=True
            )
            return
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
    await cog.filing.start_filing(interaction.user, interaction.guild, template_id, dm)


# ---------------------------------------------------------------------------
# Review forum (persistent): pending (+ signer handoff) -> approved -> published
# ---------------------------------------------------------------------------

class SignatureFieldsModal(discord.ui.Modal):
    """Generic modal collecting a set of fields' values via typed text input.

    Shared by the approval-time judge-fields collection and the signer
    handoff Sign flow — both just need "type your name/etc. into N boxes".
    """

    def __init__(
        self,
        title: str,
        fields: list[dict],
        on_submit_callback: Callable[[discord.Interaction, dict[str, str]], Awaitable[None]],
    ):
        super().__init__(title=title)
        self.field_keys = [f["key"] for f in fields]
        self._on_submit_callback = on_submit_callback
        for field in fields[:5]:
            self.add_item(
                discord.ui.TextInput(
                    label=field["label"][:45],
                    required=field.get("required", True),
                    style=discord.TextStyle.paragraph if field.get("type") == "text" else discord.TextStyle.short,
                    max_length=1000 if field.get("type") == "text" else 200,
                )
            )

    async def on_submit(self, interaction: discord.Interaction):
        answers = {key: item.value for key, item in zip(self.field_keys, self.children)}
        await self._on_submit_callback(interaction, answers)


async def _finish_approval(
    interaction: discord.Interaction,
    filing_id: str,
    judge_answers: dict[str, str],
    origin_message: discord.Message,
) -> None:
    await interaction.response.defer(ephemeral=True)
    cog = interaction.client.cogs["Filecab"]
    ok = await cog.filing.approve(interaction.guild, filing_id, interaction.user, judge_answers)
    if not ok:
        await interaction.followup.send(
            "⚠️ Couldn't approve — either this filing isn't pending anymore, or not every "
            "signer has signed yet.",
            ephemeral=True,
        )
        return
    await origin_message.edit(view=ApprovedDocumentView(filing_id))
    await interaction.followup.send(
        "✅ Approved and filed. Use **Make Public** on the thread whenever it's ready to go live.",
        ephemeral=True,
    )


def _assign_button_appearance(label: str, state: dict) -> tuple[discord.ButtonStyle, str, bool]:
    status = state.get("status", "unassigned")
    if status == "signed":
        return discord.ButtonStyle.green, f"✅ {label}: signed", True
    if status == "pending":
        return discord.ButtonStyle.grey, f"⏳ {label}: awaiting reply", True
    if status == "declined":
        return discord.ButtonStyle.red, f"🔁 Reassign {label}", False
    return discord.ButtonStyle.blurple, f"Assign {label}", False


class _AssignButton(discord.ui.Button):
    """One button per handoff signer role on the review-forum post."""

    def __init__(self, filing_id: str, role: str, label: str, state: dict):
        style, text, disabled = _assign_button_appearance(label, state)
        super().__init__(
            label=text,
            style=style,
            disabled=disabled,
            custom_id=f"filecab:assign:{filing_id}:{role}",
        )
        self.filing_id = filing_id
        self.role = role
        self.signer_label = label

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.cogs["Filecab"]
        role_id = await cog.config.guild(interaction.guild).approval_role()
        if not await can_review(interaction, role_id):
            await interaction.response.send_message(
                "⚠️ You don't have permission to assign signers.", ephemeral=True
            )
            return
        view = _AssignUserSelectView(self.filing_id, self.role, self.signer_label)
        await interaction.response.send_message(
            f"Select the **{self.signer_label}** for this filing:", view=view, ephemeral=True
        )
        view.message = await interaction.original_response()


class _AssignUserSelectView(_ExpiringView):
    """Ephemeral one-shot UserSelect shown when staff click an Assign button."""

    def __init__(self, filing_id: str, role: str, label: str):
        super().__init__(timeout=120)
        self.add_item(self._Select(filing_id, role, label))

    class _Select(discord.ui.UserSelect):
        def __init__(self, filing_id: str, role: str, label: str):
            super().__init__(placeholder=f"Select the {label}…")
            self.filing_id = filing_id
            self.role = role

        async def callback(self, interaction: discord.Interaction):
            member = self.values[0]
            await interaction.response.defer(ephemeral=True)
            cog = interaction.client.cogs["Filecab"]
            ok = await cog.filing.assign_signer(interaction.guild, self.filing_id, self.role, member)
            if ok:
                await interaction.followup.send(
                    f"✅ Sent the signing request to {member.mention}.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⚠️ Couldn't DM {member.mention} — ask them to enable DMs from server "
                    "members and try again.",
                    ephemeral=True,
                )


class FilingReviewView(discord.ui.View):
    """Review-forum view: one Assign button per handoff signer role, plus Approve/Deny.

    Approve is disabled until every handoff role has signed.
    """

    def __init__(self, config: Config, bot, filing_id: str, spec: dict, signers_state: dict):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.filing_id = filing_id
        self.spec = spec

        self.children[0].custom_id = f"filecab:approve:{filing_id}"
        self.children[1].custom_id = f"filecab:deny:{filing_id}"
        self.children[0].disabled = not all(
            s.get("status") == "signed" for s in signers_state.values()
        )

        for signer in TemplateManager.handoff_signers(spec):
            role = signer["role"]
            state = signers_state.get(role, {"status": "unassigned"})
            self.add_item(_AssignButton(filing_id, role, signer["label"], state))

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
        cog = interaction.client.cogs["Filecab"]
        judge_fields = cog.templates.approval_judge_fields(self.spec)
        origin_message = interaction.message

        if judge_fields:
            async def _on_submit(modal_interaction: discord.Interaction, answers: dict[str, str]):
                await _finish_approval(modal_interaction, self.filing_id, answers, origin_message)

            await interaction.response.send_modal(
                SignatureFieldsModal("Approve & Sign", judge_fields, _on_submit)
            )
        else:
            await _finish_approval(interaction, self.filing_id, {}, origin_message)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.red, custom_id="filecab:deny:_")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._can_review(interaction):
            await interaction.response.send_message(
                "⚠️ You don't have permission to review filings.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.cogs["Filecab"]
        await cog.filing.deny(interaction.guild, self.filing_id)
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send("❌ Denied.", ephemeral=True)


class SignerRequestView(discord.ui.View):
    """Persistent Sign/Decline buttons DM'd to an assigned handoff signer."""

    def __init__(self, filing_id: str, role: str, guild_id: int):
        super().__init__(timeout=None)
        self.filing_id = filing_id
        self.role = role
        self.guild_id = guild_id
        self.children[0].custom_id = f"filecab:sign:{filing_id}:{role}"
        self.children[1].custom_id = f"filecab:decline:{filing_id}:{role}"

    @discord.ui.button(label="✅ Sign", style=discord.ButtonStyle.green, custom_id="filecab:sign:_:_")
    async def sign(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        guild = cog.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message(
                "⚠️ Something went wrong finding the server this filing belongs to.", ephemeral=True
            )
            return
        published = await cog.config.guild(guild).published_documents()
        record = published.get(self.filing_id)
        spec = cog.templates.get(record["template_id"]) if record else None
        fields = cog.templates.signer_fields(spec, self.role) if spec else []
        if not fields:
            await interaction.response.send_message(
                "⚠️ This filing is no longer available.", ephemeral=True
            )
            return

        origin_message = interaction.message

        async def _on_submit(modal_interaction: discord.Interaction, answers: dict[str, str]):
            await modal_interaction.response.defer(ephemeral=True)
            ok = await cog.filing.sign(guild, self.filing_id, self.role, modal_interaction.user.id, answers)
            if not ok:
                await modal_interaction.followup.send(
                    "⚠️ This request is no longer pending.", ephemeral=True
                )
                return
            await origin_message.edit(
                content=origin_message.content + "\n\n✅ You signed this document. Thank you!",
                view=None,
            )
            await modal_interaction.followup.send("✅ Signed — thanks!", ephemeral=True)

        await interaction.response.send_modal(SignatureFieldsModal("Sign Document", fields, _on_submit))

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red, custom_id="filecab:decline:_:_")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        guild = cog.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message(
                "⚠️ Something went wrong finding the server this filing belongs to.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        ok = await cog.filing.decline_signer(guild, self.filing_id, self.role, interaction.user.id)
        if not ok:
            await interaction.followup.send("⚠️ This request is no longer pending.", ephemeral=True)
            return
        await interaction.message.edit(
            content=interaction.message.content + "\n\n❌ You declined to sign this document.",
            view=None,
        )
        await interaction.followup.send("Declined. Staff have been notified.", ephemeral=True)


class ApprovedDocumentView(discord.ui.View):
    """Persistent view shown after approval: on file, not yet public."""

    def __init__(self, filing_id: str):
        super().__init__(timeout=None)
        self.filing_id = filing_id
        self.children[0].custom_id = f"filecab:makepublic:{filing_id}"

    @discord.ui.button(label="🌐 Make Public", style=discord.ButtonStyle.blurple, custom_id="filecab:makepublic:_")
    async def make_public(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_conf_role = await interaction.client.cogs["Filecab"].config.guild(interaction.guild).approval_role()
        if not await can_review(interaction, guild_conf_role):
            await interaction.response.send_message(
                "⚠️ You don't have permission to publish filings.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.cogs["Filecab"]
        url = await cog.filing.make_public(interaction.guild, self.filing_id)
        button.disabled = True
        button.label = "✅ Published"
        await interaction.message.edit(view=self)
        if url:
            await interaction.followup.send(
                f"🌐 Pushed — {url}\nAnnouncing it live in the thread in a couple minutes, "
                "once the site's finished rebuilding.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "🌐 Marked published, but site publishing isn't wired up yet — announced locally only.",
                ephemeral=True,
            )


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

class SettingsPanelView(_ExpiringView):
    def __init__(self, config: Config, bot):
        super().__init__(timeout=600)
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

    @discord.ui.button(label="Reload Templates", style=discord.ButtonStyle.blurple, row=3)
    async def reload_templates(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        templates = cog.templates.reload()
        if templates:
            listing = "\n".join(f"• {spec['title']} (`{tid}`)" for tid, spec in templates.items())
        else:
            listing = "None found."
        await interaction.response.send_message(
            f"🔄 Reloaded. **{len(templates)}** template(s) loaded:\n{listing}", ephemeral=True
        )

    @discord.ui.button(label="Refresh Templates from Repo", style=discord.ButtonStyle.blurple, row=3)
    async def refresh_templates(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        site_repo = await self.config.site_repo()
        if not site_repo or "/" not in site_repo:
            await interaction.response.send_message(
                "⚠️ No site repository configured yet — use **Change Site Repo** first.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        owner, repo = site_repo.split("/", 1)
        branch = await self.config.site_branch()
        count = await cog.templates.refresh_from_repo(cog.github, owner, repo, branch)
        await interaction.followup.send(
            f"🔄 Fetched **{count}** template(s) from `{site_repo}`.", ephemeral=True
        )

    @discord.ui.button(label="Change Site Repo", style=discord.ButtonStyle.blurple, row=4)
    async def change_site_repo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SiteRepoModal(self.config))

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

    @discord.ui.button(label="Template Access", style=discord.ButtonStyle.grey, row=4)
    async def template_access(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        templates = cog.templates.all_templates()
        if not templates:
            await interaction.response.send_message("No templates are loaded yet.", ephemeral=True)
            return
        access = await self.config.guild(interaction.guild).template_access()
        view = TemplateAccessSelectView(self.config, templates, access)
        await interaction.response.send_message(
            "Select a document type to control who can file it:", view=view, ephemeral=True
        )
        view.message = await interaction.original_response()

    @discord.ui.button(label="Manage Documents", style=discord.ButtonStyle.grey, row=4)
    async def manage_documents(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_conf = self.config.guild(interaction.guild)
        published = await guild_conf.published_documents()
        manageable = {k: v for k, v in published.items() if v.get("status") != "pending"}
        if not manageable:
            await interaction.response.send_message("No documents to manage.", ephemeral=True)
            return
        view = ManageDocumentsView(self.config, self.bot, manageable)
        await interaction.response.send_message(
            "Select a document to take down or permanently delete:", view=view, ephemeral=True
        )
        view.message = await interaction.original_response()


class TemplateAccessSelectView(_ExpiringView):
    """Ephemeral view: pick a template to view/edit its filing-access gate."""

    def __init__(self, config: Config, templates: dict[str, dict], access: dict[str, list]):
        super().__init__(timeout=180)
        self.config = config
        options = []
        for template_id, spec in list(templates.items())[:25]:
            gated_count = len(access.get(template_id, []))
            description = f"Gated to {gated_count} role(s)" if gated_count else "Open to everyone"
            options.append(
                discord.SelectOption(label=spec["title"][:100], value=template_id, description=description)
            )
        self.add_item(self._TemplateSelect(options))

    class _TemplateSelect(discord.ui.Select):
        def __init__(self, options: list[discord.SelectOption]):
            super().__init__(placeholder="Select a document type…", options=options)

        async def callback(self, interaction: discord.Interaction):
            cog = interaction.client.cogs["Filecab"]
            template_id = self.values[0]
            spec = cog.templates.get(template_id)
            title = spec["title"] if spec else template_id

            access = await self.view.config.guild(interaction.guild).template_access()
            current_roles = [interaction.guild.get_role(rid) for rid in access.get(template_id, [])]
            current_roles = [r for r in current_roles if r is not None]
            summary = (
                "Currently open to **everyone**."
                if not current_roles
                else "Currently gated to: " + ", ".join(r.mention for r in current_roles)
            )

            gate_view = TemplateGateRoleView(self.view.config, template_id, title)
            await interaction.response.edit_message(
                content=(
                    f"**{title}**\n{summary}\n\n"
                    "Select the role(s) allowed to file this, or clear it below to open it "
                    "back up to everyone."
                ),
                view=gate_view,
            )
            gate_view.message = await interaction.original_response()


class TemplateGateRoleView(_ExpiringView):
    """Ephemeral view: set or clear one template's filing-access gate roles."""

    def __init__(self, config: Config, template_id: str, title: str):
        super().__init__(timeout=120)
        self.config = config
        self.template_id = template_id
        self.title = title
        self.add_item(self._RoleSelect(template_id, title))

    class _RoleSelect(discord.ui.RoleSelect):
        def __init__(self, template_id: str, title: str):
            super().__init__(
                placeholder=f"Select allowed role(s) for {title}…"[:150],
                min_values=1,
                max_values=25,
            )
            self.template_id = template_id
            self.title = title

        async def callback(self, interaction: discord.Interaction):
            async with self.view.config.guild(interaction.guild).template_access() as access:
                access[self.template_id] = [r.id for r in self.values]
            mentions = ", ".join(r.mention for r in self.values)
            await interaction.response.edit_message(
                content=f"✅ **{self.title}** is now restricted to: {mentions}", view=None
            )

    @discord.ui.button(label="Open to Everyone", style=discord.ButtonStyle.red, row=1)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.config.guild(interaction.guild).template_access() as access:
            access.pop(self.template_id, None)
        await interaction.response.edit_message(
            content=f"✅ **{self.title}** is now open to everyone.", view=None
        )


class ManageDocumentsView(_ExpiringView):
    """Ephemeral view for picking a previously filed document to take down or delete."""

    def __init__(self, config: Config, bot, documents: dict[str, dict]):
        super().__init__(timeout=120)
        self.config = config
        self.bot = bot
        options = [
            discord.SelectOption(
                label=f"{rec['title']} ({filing_id})"[:100],
                description=f"Status: {rec.get('status', 'unknown')}",
                value=filing_id,
            )
            for filing_id, rec in list(documents.items())[:25]
        ]
        self.add_item(self._DocumentSelect(documents, options))

    class _DocumentSelect(discord.ui.Select):
        def __init__(self, documents: dict[str, dict], options: list[discord.SelectOption]):
            super().__init__(placeholder="Select a document…", options=options)
            self.documents = documents

        async def callback(self, interaction: discord.Interaction):
            filing_id = self.values[0]
            record = self.documents[filing_id]
            view = DocumentActionView(self.view.config, self.view.bot, filing_id, record)
            await interaction.response.edit_message(
                content=f"**{record['title']}** (`{filing_id}`) — status: {record.get('status')}",
                view=view,
            )
            view.message = await interaction.original_response()


class DocumentActionView(_ExpiringView):
    """Ephemeral view: choose what to do with one filed document."""

    def __init__(self, config: Config, bot, filing_id: str, record: dict):
        super().__init__(timeout=120)
        self.config = config
        self.bot = bot
        self.filing_id = filing_id
        self.record = record
        # children[0] is the "Take Down" button (declared first below) — nothing to
        # unpublish/remove if the record never made it to approved/published.
        self.children[0].disabled = record.get("status") not in ("approved", "published")

    @discord.ui.button(label="🗑️ Take Down", style=discord.ButtonStyle.grey)
    async def take_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        ok = await cog.filing.takedown(interaction.guild, self.filing_id)
        if ok:
            await interaction.response.edit_message(
                content=(
                    f"🗑️ Took down **{self.record['title']}** (`{self.filing_id}`) — unpublished "
                    "and removed the rendered file. The record is kept on file for the audit "
                    "trail; use **Delete Permanently** to erase it entirely."
                ),
                view=None,
            )
        else:
            await interaction.response.edit_message(content="⚠️ Couldn't take it down.", view=None)

    @discord.ui.button(label="❌ Delete Permanently", style=discord.ButtonStyle.red)
    async def delete_permanently(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = _ConfirmDeleteView(self.filing_id, self.record)
        await interaction.response.edit_message(
            content=(
                f"⚠️ Permanently delete **{self.record['title']}** (`{self.filing_id}`)? This "
                "erases the stored answers and cannot be undone."
            ),
            view=view,
        )
        view.message = await interaction.original_response()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


class _ConfirmDeleteView(_ExpiringView):
    """Ephemeral confirmation step before a permanent, unrecoverable delete."""

    def __init__(self, filing_id: str, record: dict):
        super().__init__(timeout=60)
        self.filing_id = filing_id
        self.record = record

    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.red)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        ok = await cog.filing.purge(interaction.guild, self.filing_id)
        if ok:
            await interaction.response.edit_message(
                content=f"❌ Permanently deleted **{self.record['title']}** (`{self.filing_id}`).",
                view=None,
            )
        else:
            await interaction.response.edit_message(content="⚠️ Couldn't delete it.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)
