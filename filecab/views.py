"""All Discord UI views and modals for the Filecab cog."""
from __future__ import annotations
import logging
from typing import Awaitable, Callable
import discord
from redbot.core import Config
from .template_manager import TemplateManager
from .utils import can_file_template, can_review, normalize_base_url

log = logging.getLogger("red.Filecab")


def build_template_options(cog, include_staff_authored: bool = False) -> list[discord.SelectOption]:
    """Build select options from the cog's currently loaded templates."""
    templates = cog.templates
    return [
        discord.SelectOption(label=spec["title"], value=template_id)
        for template_id, spec in templates.all_templates().items()
        if include_staff_authored or not templates.is_staff_authored(spec)
    ][:25]


async def post_document_panel(guild: discord.Guild, config: Config, bot) -> discord.Message | None:
    """Post (or re-post) the document-type select panel to the configured channel.

    If an old panel message exists (from a previous post), it is deleted first
    so only one panel is ever live at a time.
    """
    cog = bot.cogs["Filecab"]
    options = build_template_options(cog)
    if not options:
        return None

    guild_conf = config.guild(guild)
    channel_id = await guild_conf.document_channel()
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return None

    old_msg_id = await guild_conf.panel_message_id()
    if old_msg_id:
        try:
            old_msg = await channel.fetch_message(old_msg_id)
            await old_msg.delete()
        except (discord.HTTPException, discord.NotFound):
            pass

    embed = discord.Embed(
        title="📁 File a Document",
        description="Select a document type below to begin filing it.",
        color=discord.Color.blurple(),
    )
    view = TemplateSelectView(config, bot, options)
    msg = await channel.send(embed=embed, view=view)
    await guild_conf.panel_message_id.set(msg.id)
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
            description=(
                "Select the **review category** — each filing gets its own private text "
                "channel created under it, with Approve/Deny buttons, and the filer added "
                "to just that one channel (same mechanism as `forms`' ticket channels, not "
                "threads). Deny `@everyone` View Channel on the category and grant it to "
                "staff, same as any staff-only space; the bot's role needs **Manage "
                "Channels** and **Manage Roles** on the category to create channels there "
                "with per-member overwrites — if your `forms` ticket category already "
                "works, copy the bot's permissions from there."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Setup cancelled.", view=None, embed=None)


class WizardStep2View(_WizardStepView):
    """Step 2: select the review category — filings get their own private channel under it."""

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select the review category…",
        channel_types=[discord.ChannelType.category],
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self._selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._selected is None:
            await interaction.response.send_message("⚠️ Please select a category first.", ephemeral=True)
            return
        await self.config.guild_from_id(self.guild_id).document_review_category.set(self._selected.id)
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

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
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

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
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

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
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

    @discord.ui.button(label="Skip for Now", style=discord.ButtonStyle.grey)
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

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
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


class _ConfirmFilingView(_ExpiringView):
    """Ephemeral view: confirm button shown after selecting a template from the panel."""

    def __init__(self, template_id: str, title: str):
        super().__init__(timeout=120)
        self.template_id = template_id
        self.title = title

    @discord.ui.button(label="📄 File Document", style=discord.ButtonStyle.blurple)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        button.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass
        await _start_filing_from_select(interaction, self.template_id, defer=False)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


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
            spec = interaction.client.cogs["Filecab"].templates.get(self.values[0])
            title = spec["title"] if spec else self.values[0]
            view = _ConfirmFilingView(self.values[0], title)
            await interaction.response.send_message(
                f"**{title}** — ready to file?",
                view=view,
                ephemeral=True,
            )
            view.message = await interaction.original_response()


class StaffFileSelectView(_ExpiringView):
    """Ephemeral view for `filecab file`: staff can file any template, including
    judge-authored ones with no citizen applicant role. Access gates don't apply
    here — `filecab file` is already staff/admin-only.

    `filecab_file` sends this via `ctx.send(..., ephemeral=True)`, but Red's
    hybrid commands silently drop `ephemeral` when invoked with a text prefix
    rather than a slash command — the message would otherwise be visible (and
    clickable) to any member in the channel. `interaction_check` re-validates
    staff/admin on every click so a prefix invocation can't turn this into an
    unrestricted "file anything, gates included" tool.
    """

    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(timeout=120)
        self.add_item(self._TemplateSelect(options))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cog = interaction.client.cogs["Filecab"]
        approval_role_id = await cog.config.guild(interaction.guild).approval_role()
        if await can_review(interaction, approval_role_id):
            return True
        await interaction.response.send_message(
            "⚠️ You don't have permission to use this.", ephemeral=True
        )
        return False

    class _TemplateSelect(discord.ui.Select):
        def __init__(self, options: list[discord.SelectOption]):
            super().__init__(placeholder="Select a document type to file…", options=options)

        async def callback(self, interaction: discord.Interaction):
            await _start_filing_from_select(interaction, self.values[0], enforce_gate=False)


async def _start_filing_from_select(
    interaction: discord.Interaction, template_id: str, *, enforce_gate: bool = True, defer: bool = True
) -> None:
    cog = interaction.client.cogs["Filecab"]
    if enforce_gate:
        access = await cog.config.guild(interaction.guild).template_access()
        allowed_role_ids = access.get(template_id, [])
        if allowed_role_ids and not await can_file_template(interaction, allowed_role_ids):
            spec = cog.templates.get(template_id)
            title = spec["title"] if spec else "this document"
            parts = [
                r.mention if (r := interaction.guild.get_role(rid)) else f"a deleted role (`{rid}`)"
                for rid in allowed_role_ids
            ]
            message = (
                f"⚠️ You don't have permission to file **{title}** — it's restricted to: "
                + ", ".join(parts)
                + "."
            )
            log.info(
                "Gate denied filing of %r to %s (id %s) in guild %s — requires roles %s",
                template_id,
                interaction.user.display_name,
                interaction.user.id,
                interaction.guild.id,
                allowed_role_ids,
            )
            if defer:
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
            return
    try:
        dm = await interaction.user.create_dm()
    except discord.Forbidden:
        if defer:
            await interaction.response.send_message(
                "⚠️ I couldn't DM you. Please enable DMs from server members and try again.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "⚠️ I couldn't DM you. Please enable DMs from server members and try again.",
                ephemeral=True,
            )
        return
    if defer:
        await interaction.response.send_message(
            "📬 Check your DMs — I've sent you the first question!", ephemeral=True
        )
    else:
        await interaction.followup.send(
            "📬 Check your DMs — I've sent you the first question!", ephemeral=True
        )
    await cog.filing.start_filing(interaction.user, interaction.guild, template_id, dm)


# ---------------------------------------------------------------------------
# Review channel (persistent): pending (+ signer handoff) -> approved -> published
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
        "✅ Approved and filed. Use **Make Public** in this channel whenever it's ready to go live.",
        ephemeral=True,
    )


def _sign_button_appearance(label: str, state: dict) -> tuple[discord.ButtonStyle, str, bool]:
    status = state.get("status", "open")
    if status == "signed":
        return discord.ButtonStyle.green, f"✅ {label}: signed", True
    if status == "stale":
        return discord.ButtonStyle.red, f"🔁 Re-sign Needed: {label}", False
    return discord.ButtonStyle.blurple, f"✍️ Sign as {label}", False


class _SignButton(discord.ui.Button):
    """One button per handoff signer role on the review-channel post.

    Open to anyone with access to the channel — not staff-gated — same as
    Edit Field. There's no separate assign-a-person-then-DM-them step: staff
    add the actual signer to the channel via Add Person if they aren't
    already in there (the filer always is), and that person clicks this
    directly, right where the document already is, same pattern as the
    judge fields collected on Approve. This sidesteps DMs (and their privacy
    settings) for signing entirely, rather than working around them.
    """

    def __init__(self, filing_id: str, role: str, label: str, state: dict):
        style, text, disabled = _sign_button_appearance(label, state)
        super().__init__(
            label=text,
            style=style,
            disabled=disabled,
            custom_id=f"filecab:signas:{filing_id}:{role}",
        )
        self.filing_id = filing_id
        self.role = role
        self.signer_label = label

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.cogs["Filecab"]
        published = await cog.config.guild(interaction.guild).published_documents()
        record = published.get(self.filing_id)
        if not record or record.get("status") != "pending":
            await interaction.response.send_message(
                "⚠️ This filing isn't open for signing anymore.", ephemeral=True
            )
            return
        spec = cog.templates.get(record["template_id"])
        fields = cog.templates.signer_fields(spec, self.role) if spec else []
        if not fields:
            await interaction.response.send_message(
                "⚠️ This filing's template is no longer available.", ephemeral=True
            )
            return

        async def _on_submit(modal_interaction: discord.Interaction, answers: dict[str, str]):
            await modal_interaction.response.defer(ephemeral=True)
            ok = await cog.filing.sign(
                modal_interaction.guild, self.filing_id, self.role, modal_interaction.user.id, answers
            )
            if not ok:
                await modal_interaction.followup.send(
                    "⚠️ Couldn't record that signature — this filing may have changed.", ephemeral=True
                )
                return
            await modal_interaction.followup.send(
                f"✅ Signed as **{self.signer_label}** — thanks!", ephemeral=True
            )

        await interaction.response.send_modal(
            SignatureFieldsModal(f"Sign as {self.signer_label}"[:45], fields, _on_submit)
        )


class FilingReviewView(discord.ui.View):
    """Review-channel view: one Sign button per handoff signer role, plus Approve/Deny.

    Approve is disabled until every handoff role has signed. `spec` can be
    None — the filing's template was deleted from the site repo since it was
    filed — in which case Approve is force-disabled (there's no schema left
    to safely collect judge fields or render the document) and no Sign
    buttons are shown, but Deny still works, so a restart doesn't strand the
    filing with an entirely dead review post.
    """

    def __init__(self, config: Config, bot, filing_id: str, spec: dict | None, signers_state: dict):
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot
        self.filing_id = filing_id
        self.spec = spec

        self.children[0].custom_id = f"filecab:approve:{filing_id}"
        self.children[1].custom_id = f"filecab:deny:{filing_id}"
        self.children[2].custom_id = f"filecab:editfield:{filing_id}"
        self.children[3].custom_id = f"filecab:addperson:{filing_id}"

        if spec is None:
            self.children[0].disabled = True
            self.children[0].label = "⚠️ Template Missing"
            self.children[2].disabled = True
            return

        self.children[0].disabled = not all(
            s.get("status") == "signed" for s in signers_state.values()
        )
        for signer in TemplateManager.handoff_signers(spec):
            role = signer["role"]
            state = signers_state.get(role, {"status": "open"})
            self.add_item(_SignButton(filing_id, role, signer["label"], state))

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
        # Disable + save *before* calling filing.deny() — that call may archive and
        # delete this very channel (see FilingManager._close_channel), so nothing
        # below can rely on the message or channel still existing afterward.
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass
        cog = interaction.client.cogs["Filecab"]
        await cog.filing.deny(interaction.guild, self.filing_id)
        try:
            await interaction.followup.send("❌ Denied.", ephemeral=True)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="✏️ Edit Field", style=discord.ButtonStyle.blurple, custom_id="filecab:editfield:_")
    async def edit_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open to anyone with access to this channel — not staff-gated, unlike its
        sibling buttons. The filer is meant to be able to fix their own answers here."""
        cog = interaction.client.cogs["Filecab"]
        published = await cog.config.guild(interaction.guild).published_documents()
        record = published.get(self.filing_id)
        if not record or record.get("status") != "pending":
            await interaction.response.send_message(
                "⚠️ This filing isn't open for editing anymore.", ephemeral=True
            )
            return
        options = [
            discord.SelectOption(
                label=field["label"][:100],
                value=field["key"],
                description=f"Current: {record['answers'].get(field['key']) or '(empty)'}"[:100],
            )
            for field in TemplateManager.prompted_fields(self.spec)
            if field.get("filled_by") == "applicant"
        ][:25]
        if not options:
            await interaction.response.send_message(
                "⚠️ There's nothing on this template that can be edited here.", ephemeral=True
            )
            return
        view = EditFieldSelectView(self.filing_id, self.spec, record, options)
        await interaction.response.send_message("Select a field to edit:", view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @discord.ui.button(label="👤 Add Person", style=discord.ButtonStyle.blurple, custom_id="filecab:addperson:_")
    async def add_person(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._can_review(interaction):
            await interaction.response.send_message(
                "⚠️ You don't have permission to add people to this channel.", ephemeral=True
            )
            return
        view = _AddPersonSelectView(self.filing_id)
        await interaction.response.send_message(
            "Select who to add to this channel:", view=view, ephemeral=True
        )
        view.message = await interaction.original_response()


class _AddPersonSelectView(_ExpiringView):
    """Ephemeral one-shot UserSelect shown when staff click Add Person."""

    def __init__(self, filing_id: str):
        super().__init__(timeout=120)
        self.add_item(self._Select(filing_id))

    class _Select(discord.ui.UserSelect):
        def __init__(self, filing_id: str):
            super().__init__(placeholder="Select a member to add…")
            self.filing_id = filing_id

        async def callback(self, interaction: discord.Interaction):
            member = self.values[0]
            await interaction.response.defer(ephemeral=True)
            cog = interaction.client.cogs["Filecab"]
            ok = await cog.filing.add_person_to_channel(
                interaction.guild, self.filing_id, member, interaction.user
            )
            if ok:
                await interaction.followup.send(f"✅ Added {member.mention} to this channel.", ephemeral=True)
            else:
                await interaction.followup.send(
                    "⚠️ Couldn't add them — check the bot's permissions on this channel.", ephemeral=True
                )


class EditFieldSelectView(_ExpiringView):
    """Ephemeral view: pick which field to edit on a pending filing."""

    def __init__(self, filing_id: str, spec: dict, record: dict, options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.filing_id = filing_id
        self.spec = spec
        self.record = record
        self.add_item(self._FieldSelect(options))

    class _FieldSelect(discord.ui.Select):
        def __init__(self, options: list[discord.SelectOption]):
            super().__init__(placeholder="Select a field to edit…", options=options)

        async def callback(self, interaction: discord.Interaction):
            view: EditFieldSelectView = self.view
            field_key = self.values[0]
            field = next(f for f in view.spec["fields"] if f["key"] == field_key)
            current_value = view.record["answers"].get(field_key, "")

            signed_labels = []
            for role, state in view.record.get("signers", {}).items():
                if state.get("status") != "signed":
                    continue
                signer_spec = next((s for s in view.spec.get("signers", []) if s["role"] == role), None)
                signed_labels.append(signer_spec["label"] if signer_spec else role)

            if signed_labels:
                warn_view = _EditFieldWarningView(view.filing_id, field, current_value)
                await interaction.response.edit_message(
                    content=(
                        f"⚠️ **{', '.join(signed_labels)}** already signed this document. Editing "
                        "**"
                        f"{field['label']}"
                        "** will invalidate their signature(s) — they'll need to re-sign before "
                        "this can be approved. Continue?"
                    ),
                    view=warn_view,
                )
                warn_view.message = await interaction.original_response()
            else:
                await interaction.response.send_modal(
                    EditFieldModal(view.filing_id, field, current_value)
                )


class _EditFieldWarningView(_ExpiringView):
    """Ephemeral confirm/cancel shown before editing a field on an already-signed filing."""

    def __init__(self, filing_id: str, field: dict, current_value: str):
        super().__init__(timeout=120)
        self.filing_id = filing_id
        self.field = field
        self.current_value = current_value

    @discord.ui.button(label="✏️ Continue to Edit", style=discord.ButtonStyle.blurple)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            EditFieldModal(self.filing_id, self.field, self.current_value)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


class EditFieldModal(discord.ui.Modal):
    """Collects a new value for one field on a pending filing."""

    def __init__(self, filing_id: str, field: dict, current_value: str):
        super().__init__(title=f"Edit: {field['label']}"[:45])
        self.filing_id = filing_id
        self.field_key = field["key"]
        max_len = 1000 if field.get("type") == "text" else 200
        self.value_input = discord.ui.TextInput(
            label=field["label"][:45],
            style=discord.TextStyle.paragraph if field.get("type") == "text" else discord.TextStyle.short,
            default=(current_value[:max_len] if current_value else None),
            required=field.get("required", True),
            max_length=max_len,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.cogs["Filecab"]
        ok = await cog.filing.edit_field(
            interaction.guild, self.filing_id, self.field_key, self.value_input.value, interaction.user
        )
        if ok:
            await interaction.followup.send("✅ Field updated.", ephemeral=True)
        else:
            await interaction.followup.send(
                "⚠️ Couldn't update — this filing may no longer be pending.", ephemeral=True
            )


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
        button.style = discord.ButtonStyle.green
        await interaction.message.edit(view=self)
        if url:
            await interaction.followup.send(
                f"🌐 Pushed — {url}\nAnnouncing it live in this channel in a couple minutes, "
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
    """`filecab_settings` sends this via `ctx.send(..., ephemeral=True)`, but Red's
    hybrid commands silently drop `ephemeral` when invoked with a text prefix rather
    than a slash command — the panel would otherwise be visible (and clickable) to
    any member in the channel. `interaction_check` re-validates staff/admin on every
    click, matching the per-click checks already used on the review-channel views.
    """

    def __init__(self, config: Config, bot):
        super().__init__(timeout=600)
        self.config = config
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        approval_role_id = await self.config.guild(interaction.guild).approval_role()
        if await can_review(interaction, approval_role_id):
            return True
        await interaction.response.send_message(
            "⚠️ You don't have permission to use this.", ephemeral=True
        )
        return False

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
        placeholder="Change review category…",
        channel_types=[discord.ChannelType.category],
        row=1,
    )
    async def change_review_category(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await self.config.guild(interaction.guild).document_review_category.set(select.values[0].id)
        await interaction.response.send_message(
            f"✅ Review category set to {select.values[0].mention}.", ephemeral=True
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

    @discord.ui.button(label="🔄 Reload Templates", style=discord.ButtonStyle.blurple, row=3)
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

    @discord.ui.button(label="🔄 Refresh Templates from Repo", style=discord.ButtonStyle.blurple, row=3)
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
        # Gates are only enforced on the public panel, which never lists staff-authored
        # (judge-only) templates in the first place — configuring one here would be
        # dead configuration, so don't offer it.
        templates = {
            tid: spec for tid, spec in cog.templates.all_templates().items()
            if not cog.templates.is_staff_authored(spec)
        }
        if not templates:
            await interaction.response.send_message(
                "No citizen-facing templates are loaded yet.", ephemeral=True
            )
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

    @discord.ui.button(label="📋 Log Forum", style=discord.ButtonStyle.grey, row=4)
    async def log_forum(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Optional — a forum channel gets its own dedicated select here rather than a
        row on this already-full (5/5) panel. Leaving it unset just means Make Public
        never archives/deletes review channels, same as before this existed."""
        view = LogForumSelectView(self.config)
        await interaction.response.send_message(
            "Select the forum where published filings get archived (optional):",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


class LogForumSelectView(_ExpiringView):
    """Ephemeral view: a single forum ChannelSelect for document_log_forum."""

    def __init__(self, config: Config):
        super().__init__(timeout=120)
        self.config = config
        self.add_item(self._Select())

    class _Select(discord.ui.ChannelSelect):
        def __init__(self):
            super().__init__(
                placeholder="Select a forum channel…",
                channel_types=[discord.ChannelType.forum],
            )

        async def callback(self, interaction: discord.Interaction):
            view: LogForumSelectView = self.view
            await view.config.guild(interaction.guild).document_log_forum.set(self.values[0].id)
            await interaction.response.edit_message(
                content=f"✅ Log forum set to {self.values[0].mention}.", view=None
            )


class TemplateAccessSelectView(_ExpiringView):
    """Ephemeral view: pick a template to view/edit its filing-access gate."""

    def __init__(self, config: Config, templates: dict[str, dict], access: dict[str, list]):
        super().__init__(timeout=180)
        self.config = config
        self.templates = templates
        self.access = access
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
            template_id = self.values[0]
            spec = self.view.templates.get(template_id)
            title = spec["title"] if spec else template_id

            # Gated/not-gated must be judged from the raw id list — same as enforcement
            # in `_start_filing_from_select` — not from ids that still resolve to a live
            # role, or a deleted role would make this claim "open to everyone" while the
            # gate actually blocks everybody.
            role_ids = self.view.access.get(template_id, [])
            if not role_ids:
                summary = "Currently open to **everyone**."
            else:
                parts = [
                    r.mention if (r := interaction.guild.get_role(rid)) else f"a deleted role (`{rid}`)"
                    for rid in role_ids
                ]
                summary = "Currently gated to: " + ", ".join(parts)

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

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select allowed role(s)…", min_values=1, max_values=25)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        async with self.config.guild(interaction.guild).template_access() as access:
            access[self.template_id] = [r.id for r in select.values]
        mentions = ", ".join(r.mention for r in select.values)
        await interaction.response.edit_message(
            content=f"✅ **{self.title}** is now restricted to: {mentions}", view=None
        )

    @discord.ui.button(label="Open to Everyone", style=discord.ButtonStyle.grey, row=1)
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
        shown = list(documents.items())[:25]
        options = [
            discord.SelectOption(
                label=f"{rec['title']} ({filing_id})"[:100],
                description=f"Status: {rec.get('status', 'unknown')}",
                value=filing_id,
            )
            for filing_id, rec in shown
        ]
        # Only carry title/status forward, not the full record — filings hold citizen
        # PII (DM answers) that the takedown/delete flow below has no need to see.
        titles = {filing_id: (rec["title"], rec.get("status")) for filing_id, rec in shown}
        self.add_item(self._DocumentSelect(titles, options))

    class _DocumentSelect(discord.ui.Select):
        def __init__(self, titles: dict[str, tuple[str, str]], options: list[discord.SelectOption]):
            super().__init__(placeholder="Select a document…", options=options)
            self.titles = titles

        async def callback(self, interaction: discord.Interaction):
            filing_id = self.values[0]
            title, status = self.titles[filing_id]
            view = DocumentActionView(filing_id, title, status)
            await interaction.response.edit_message(
                content=f"**{title}** (`{filing_id}`) — status: {status}",
                view=view,
            )
            view.message = await interaction.original_response()


class DocumentActionView(_ExpiringView):
    """Ephemeral view: choose what to do with one filed document."""

    def __init__(self, filing_id: str, title: str, status: str | None):
        super().__init__(timeout=120)
        self.filing_id = filing_id
        self.title = title
        # children[0] is the "Take Down" button (declared first below) — nothing to
        # unpublish/remove if the record never made it to approved/published.
        self.children[0].disabled = status not in ("approved", "published")

    @discord.ui.button(label="🗑️ Take Down", style=discord.ButtonStyle.grey)
    async def take_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        ok = await cog.filing.takedown(interaction.guild, self.filing_id)
        if ok:
            await interaction.response.edit_message(
                content=(
                    f"🗑️ Took down **{self.title}** (`{self.filing_id}`) — unpublished "
                    "and removed the rendered file. The record is kept on file for the audit "
                    "trail; use **Delete Permanently** to erase it entirely."
                ),
                view=None,
            )
        else:
            await interaction.response.edit_message(content="⚠️ Couldn't take it down.", view=None)

    @discord.ui.button(label="❌ Delete Permanently", style=discord.ButtonStyle.red)
    async def delete_permanently(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = _ConfirmDeleteView(self.filing_id, self.title)
        await interaction.response.edit_message(
            content=(
                f"⚠️ Permanently delete **{self.title}** (`{self.filing_id}`)? This "
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

    def __init__(self, filing_id: str, title: str):
        super().__init__(timeout=60)
        self.filing_id = filing_id
        self.title = title

    @discord.ui.button(label="❌ Confirm Delete", style=discord.ButtonStyle.red)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs["Filecab"]
        ok = await cog.filing.purge(interaction.guild, self.filing_id)
        if ok:
            await interaction.response.edit_message(
                content=f"❌ Permanently deleted **{self.title}** (`{self.filing_id}`).",
                view=None,
            )
        else:
            await interaction.response.edit_message(content="⚠️ Couldn't delete it.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelled.", view=None)
