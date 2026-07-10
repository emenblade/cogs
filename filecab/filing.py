"""DM Q&A filing flow, multi-signer handoff, approval, and publish/takedown."""
from __future__ import annotations
import asyncio
import io
from datetime import date, datetime
import discord
from redbot.core import Config
from redbot.core.bot import Red
from .template_manager import TemplateManager
from .publisher import DocumentPublisher
from .utils import build_channel_transcript, get_or_create_forum_tag, slugify

# How long to wait before announcing a filing is live, so the site's GitHub
# Action has time to rebuild/deploy before anyone clicks the link.
PUBLISH_ANNOUNCE_DELAY_SECONDS = 120


def _today() -> str:
    return date.today().isoformat()


def _truncate_for_discord(content: str) -> tuple[str, bool]:
    """Return (possibly truncated content, whether it was truncated)."""
    suffix = "\n…(see attachment)"
    if len(content) <= 2000:
        return content, False
    return content[: 2000 - len(suffix)] + suffix, True


class FilingManager:
    def __init__(
        self,
        bot: Red,
        config: Config,
        templates: TemplateManager,
        publisher: DocumentPublisher,
    ) -> None:
        self.bot = bot
        self.config = config
        self.templates = templates
        self.publisher = publisher

    async def start_filing(
        self, user: discord.User, guild: discord.Guild, template_id: str, dm: discord.DMChannel
    ) -> None:
        """Set active_filing state and send the first field's prompt via DM.

        Any leading fields whose `depends_on` condition already fails against an
        empty answers dict (unusual, but possible for a template authored oddly)
        are skipped the same way `handle_reply` skips later ones.
        """
        spec = self.templates.get(template_id)
        if not spec:
            await dm.send("❌ This document type is no longer available. Please contact staff.")
            return

        prompted = self.templates.prompted_fields(spec)
        field_index, answers = self.templates.advance_past_skipped(spec, {}, 0)

        image_path = self.templates.preview_image_path(template_id)
        if image_path is not None:
            await dm.send(
                "🖼️ Here's an example of what this document looks like — I'll ask you for "
                "each field in it now.",
                file=discord.File(str(image_path)),
            )

        if field_index >= len(prompted):
            # Every prompted field was conditionally skipped — nothing left to ask.
            await dm.send(f"👋 Filing a **{spec['title']}** — nothing else needed, submitting now.")
            await self._submit(user, guild, spec, answers)
            return

        state = {"template_id": template_id, "guild_id": guild.id, "field_index": field_index, "answers": answers}
        await self.config.user(user).active_filing.set(state)

        await dm.send(
            f"👋 Let's file a **{spec['title']}**! ({len(prompted)} question(s))\n"
            f"*Reply `cancel` at any time to cancel this filing.*\n\n"
            f"**Question {field_index + 1} of {len(prompted)}:** {prompted[field_index]['prompt']}"
        )

    async def handle_reply(
        self,
        member: discord.Member,
        guild: discord.Guild,
        state: dict,
        message: discord.Message,
    ) -> None:
        """Process one DM reply, save the answer, and advance or finish the filing."""
        spec = self.templates.get(state["template_id"])
        if not spec:
            await self.config.user(member).active_filing.set(None)
            await message.channel.send(
                "❌ This document type was removed before you finished. Filing cancelled."
            )
            return

        prompted = self.templates.prompted_fields(spec)
        answer = message.content.strip()

        if answer.lower() == "cancel":
            await self.config.user(member).active_filing.set(None)
            await message.channel.send(
                "❌ Filing cancelled. You can start again any time from the document panel."
            )
            return

        current_field = prompted[state["field_index"]]
        answers = {**state["answers"], current_field["key"]: answer}
        next_index, answers = self.templates.advance_past_skipped(spec, answers, state["field_index"] + 1)

        if next_index >= len(prompted):
            await self.config.user(member).active_filing.set(None)
            await message.channel.send("✅ **Filing complete!** Your document has been sent for staff review.")
            await self._submit(member, guild, spec, answers)
        else:
            new_state = {**state, "field_index": next_index, "answers": answers}
            await self.config.user(member).active_filing.set(new_state)
            next_field = prompted[next_index]
            await message.channel.send(
                f"**Question {next_index + 1} of {len(prompted)}:** {next_field['prompt']}"
            )

    async def _next_filing_id(self, template_id: str) -> str:
        """Mint a `<template_id>-<year>-<seq>` id from the global per-template-per-year counter."""
        year = datetime.now().year
        counter_key = f"{template_id}-{year}"
        async with self.config.filing_counters() as counters:
            seq = counters.get(counter_key, 0) + 1
            counters[counter_key] = seq
        return f"{template_id}-{year}-{seq:04d}"

    def _build_transcript(self, spec: dict, filer_label: str, answers: dict[str, str]) -> str:
        lines = [f"**Document: {spec['title']}**", f"Filed by: {filer_label}", ""]
        for field in self.templates.prompted_fields(spec):
            lines.append(f"**{field['label']}**")
            lines.append(answers.get(field["key"], ""))
            lines.append("")
        return "\n".join(lines)

    async def _submit(
        self, member: discord.Member, guild: discord.Guild, spec: dict, answers: dict[str, str]
    ) -> None:
        """Fill submission-time auto fields, mint a filing id, and post it for review."""
        template_id = spec["template_id"]
        filing_id = await self._next_filing_id(template_id)

        full_answers = dict(answers)
        for field in self.templates.auto_fields(spec, "submission"):
            full_answers[field["key"]] = _today()

        record = {
            "template_id": template_id,
            "title": spec["title"],
            "category": spec.get("category", "Uncategorized"),
            "filing_id": filing_id,
            "user_id": member.id,
            "answers": full_answers,
            "filed_date": _today(),
            "status": "pending",
            "discussion": [],
        }
        await self._post_review(member, guild, spec, filing_id, record)

    async def _post_review(
        self,
        member: discord.Member,
        guild: discord.Guild,
        spec: dict,
        filing_id: str,
        record: dict,
    ) -> None:
        """Post a Q&A transcript + Approve/Deny/Assign view to a private review channel.

        Each filing gets its own text channel created under the configured review
        category, with an explicit permission overwrite granting the filer access
        to just that one channel — the same mechanism the `forms` cog's ticket
        channels already use in production, not threads (a non-invitable private
        thread's `add_user` turned out not to reliably grant access regardless of
        the bot's permissions — see git history). The filer can see and post in
        their own filing's channel, like a support ticket, but has no visibility
        into any other filing's channel, since that isolation is an ordinary
        per-channel permission overwrite, the same as every other private channel
        on the server.

        By the time this runs, the filer has already been told (in `handle_reply`)
        that their filing was submitted — so if anything here fails partway
        through, the answers must not just vanish. The record is always saved to
        config (with channel_id/message_id left unset if the channel itself
        couldn't even be created) and the filer is told something went wrong
        rather than the filing silently disappearing with no trace anywhere.
        """
        from .views import FilingReviewView

        guild_conf = self.config.guild(guild)
        category_id = await guild_conf.document_review_category()
        category = guild.get_channel(category_id) if category_id else None
        if not category or not isinstance(category, discord.CategoryChannel):
            await member.send(
                "⚠️ Your filing was completed but staff haven't configured a review category "
                "yet — please let them know so it can be processed."
            )
            return

        record["signers"] = {
            s["role"]: {"user_id": None, "status": "unassigned", "dm_message_id": None}
            for s in self.templates.handoff_signers(spec)
        }

        transcript = self._build_transcript(spec, f"{member.mention} ({member.name})", record["answers"])
        content, overflowed = _truncate_for_discord(transcript)
        view = FilingReviewView(self.config, self.bot, filing_id, spec, record["signers"])

        # Inherit the category's own overwrites (already has @everyone denied + staff
        # allowed, same as any staff-only space) and layer on just the filer + bot.
        overwrites = dict(category.overwrites)
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
        )
        channel_name = slugify(f"{spec['title']}-{member.name}-{filing_id}", max_length=90, fallback=filing_id)

        try:
            channel = await category.create_text_channel(
                channel_name,
                overwrites=overwrites,
                reason=f"Filecab review channel for {filing_id}",
            )
        except (discord.Forbidden, discord.HTTPException):
            # Most likely cause: the bot's role is missing Manage Channels/Manage
            # Roles on the review category. There's no channel to fall back to
            # here — just make sure the filer isn't left thinking this worked,
            # and the answers are still saved below.
            try:
                await member.send(
                    "⚠️ Something went wrong setting up your filing for staff review — your "
                    "answers weren't lost, but a developer needs to check the bot's "
                    "permissions on the review category. Sorry for the trouble!"
                )
            except discord.Forbidden:
                pass
            published = await guild_conf.published_documents()
            published[filing_id] = record
            await guild_conf.published_documents.set(published)
            return

        try:
            image_path = self.templates.preview_image_path(record["template_id"])
            if image_path is not None:
                await channel.send(
                    "🖼️ Here's an example of what this document looks like.",
                    file=discord.File(str(image_path)),
                )

            # Transcript embeds raw DM answers — suppress @everyone/@here/role/other-user
            # mentions someone could try to sneak in via a free-text answer. The filer's
            # own "Filed by:" mention is bot-constructed, not user free text, so it's
            # explicitly allowed through.
            first_msg = await channel.send(
                content=content,
                view=view,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=[member], roles=False),
            )
            if overflowed:
                fp = io.BytesIO(transcript.encode("utf-8"))
                await channel.send(file=discord.File(fp, filename=f"{filing_id}.txt"))

            record["channel_id"] = channel.id
            record["message_id"] = first_msg.id
        except (discord.Forbidden, discord.HTTPException) as exc:
            try:
                await channel.send(
                    f"⚠️ Something went wrong finishing this filing's setup ({exc}) — the "
                    "filer's answers are safe on file; a developer needs to look into this."
                )
            except discord.HTTPException:
                pass
            try:
                await member.send(
                    "⚠️ Something went wrong setting up your filing for staff review — your "
                    "answers weren't lost and staff have been notified. Sorry for the trouble!"
                )
            except discord.Forbidden:
                pass

        published = await guild_conf.published_documents()
        published[filing_id] = record
        await guild_conf.published_documents.set(published)

    async def _get_channel(self, channel_id: int | None):
        """Fetch a review channel by id, falling back to the API if not cached."""
        if not channel_id:
            return None
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return channel

    async def _refresh_review_message(self, guild: discord.Guild, record: dict, spec: dict) -> None:
        """Re-render the review-channel message's view to reflect current signer state."""
        from .views import FilingReviewView

        message_id = record.get("message_id")
        channel = await self._get_channel(record.get("channel_id"))
        if not channel or not message_id:
            return
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return
        view = FilingReviewView(self.config, self.bot, record["filing_id"], spec, record.get("signers", {}))
        await message.edit(view=view)

    async def edit_field(
        self,
        guild: discord.Guild,
        filing_id: str,
        field_key: str,
        new_value: str,
        editor: discord.abc.User,
    ) -> bool:
        """Update one field's answer on a pending filing.

        Open to anyone with access to the filing's review channel, not
        staff-gated — the filer is meant to be able to fix their own answers
        here too. If any signer had already signed, editing resets them to
        "stale" (their signature no longer covers the current content) rather
        than silently leaving a signature on outdated answers; Approve stays
        locked until they're reassigned and re-sign, reusing the exact same
        Assign/Sign flow as a first-time signer.
        """
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] != "pending":
            return False

        spec = self.templates.get(record["template_id"])
        if not spec:
            return False
        field = next((f for f in spec["fields"] if f["key"] == field_key), None)
        if not field:
            return False

        old_value = record["answers"].get(field_key, "")
        record["answers"][field_key] = new_value

        invalidated = []
        for role, state in record.get("signers", {}).items():
            if state.get("status") != "signed":
                continue
            state["status"] = "stale"
            signer_spec = next((s for s in spec.get("signers", []) if s["role"] == role), None)
            invalidated.append(signer_spec["label"] if signer_spec else role)

        published[filing_id] = record
        await guild_conf.published_documents.set(published)
        await self._refresh_review_message(guild, record, spec)

        channel = await self._get_channel(record.get("channel_id"))
        if channel is not None:
            old_display = old_value or "_(empty)_"
            new_display = new_value or "_(empty)_"
            notice = f"✏️ **{field['label']}** updated by {editor.mention}: ~~{old_display}~~ → **{new_display}**"
            if invalidated:
                notice += (
                    f"\n⚠️ This invalidates the existing signature(s) from **{', '.join(invalidated)}** "
                    "— use the Assign button(s) above to have them re-sign before this can be approved."
                )
            content, _ = _truncate_for_discord(notice)
            # Old/new values are raw user-supplied text (same class of risk as the
            # original transcript) — suppress @everyone/@here/role/other-user mentions.
            try:
                await channel.send(
                    content,
                    allowed_mentions=discord.AllowedMentions(everyone=False, users=[editor], roles=False),
                )
            except discord.HTTPException:
                pass
        return True

    async def add_person_to_channel(
        self,
        guild: discord.Guild,
        filing_id: str,
        member: discord.abc.User,
        added_by: discord.abc.User,
    ) -> bool:
        """Grant an extra Discord member access to a filing's private review channel."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record:
            return False
        channel = await self._get_channel(record.get("channel_id"))
        if channel is None:
            return False
        try:
            await channel.set_permissions(
                member,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                ),
                reason=f"Filecab: added by {added_by} to filing {filing_id}",
            )
        except (discord.Forbidden, discord.HTTPException):
            return False
        try:
            await channel.send(f"👤 {member.mention} was added to this channel by {added_by.mention}.")
        except discord.HTTPException:
            pass
        return True

    async def log_review_message(
        self, guild: discord.Guild, channel: discord.TextChannel, message: discord.Message
    ) -> None:
        """Persist a human message posted in a filing's private review channel.

        The per-channel permission overwrite (the filer only having access to
        their own filing's channel) already keeps the conversation scoped
        correctly — this just keeps a durable copy in config so the discussion
        survives even if the channel is later deleted.
        """
        guild_conf = self.config.guild(guild)
        review_category_id = await guild_conf.document_review_category()
        if not review_category_id or channel.category_id != review_category_id:
            return

        published = await guild_conf.published_documents()
        record = next((r for r in published.values() if r.get("channel_id") == channel.id), None)
        if record is None:
            return

        record.setdefault("discussion", []).append({
            "author_id": message.author.id,
            "author_label": f"{message.author.display_name} ({message.author.name})",
            "content": message.content,
            "at": datetime.now().isoformat(timespec="seconds"),
        })
        published[record["filing_id"]] = record
        await guild_conf.published_documents.set(published)

    async def assign_signer(
        self, guild: discord.Guild, filing_id: str, role: str, member: discord.abc.User
    ) -> bool:
        """Assign a Discord member to a handoff signer role and DM them a sign/decline request."""
        from .views import SignerRequestView

        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] != "pending":
            return False
        spec = self.templates.get(record["template_id"])
        if not spec:
            return False
        signer_spec = next((s for s in spec.get("signers", []) if s["role"] == role), None)
        if not signer_spec or role not in record.get("signers", {}):
            return False

        filer = guild.get_member(record["user_id"])
        filer_label = f"{filer.mention} ({filer.name})" if filer else f"user ID {record['user_id']}"
        transcript = self._build_transcript(spec, filer_label, record["answers"])
        content, overflowed = _truncate_for_discord(transcript)

        try:
            dm = await member.create_dm()
            image_path = self.templates.preview_image_path(record["template_id"])
            if image_path is not None:
                await dm.send(
                    "🖼️ Here's an example of the document you're being asked to sign.",
                    file=discord.File(str(image_path)),
                )
            dm_msg = await dm.send(
                f"You've been asked to sign as **{signer_spec['label']}** on a "
                f"**{spec['title']}**, filed by {filer_label}.\n\n{content}",
                view=SignerRequestView(filing_id, role, guild.id),
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=[filer] if filer else [], roles=False
                ),
            )
            if overflowed:
                fp = io.BytesIO(transcript.encode("utf-8"))
                await dm.send(file=discord.File(fp, filename=f"{filing_id}.txt"))
        except discord.Forbidden:
            return False

        record["signers"][role] = {"user_id": member.id, "status": "pending", "dm_message_id": dm_msg.id}
        published[filing_id] = record
        await guild_conf.published_documents.set(published)
        await self._refresh_review_message(guild, record, spec)
        return True

    async def sign(
        self, guild: discord.Guild, filing_id: str, role: str, signer_id: int, field_answers: dict[str, str]
    ) -> bool:
        """Record a signer's answers for their role and mark it signed."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] != "pending":
            return False
        signer_state = record.get("signers", {}).get(role)
        if not signer_state or signer_state["status"] != "pending" or signer_state["user_id"] != signer_id:
            return False

        record["answers"].update(field_answers)
        signer_state["status"] = "signed"
        published[filing_id] = record
        await guild_conf.published_documents.set(published)

        spec = self.templates.get(record["template_id"])
        await self._refresh_review_message(guild, record, spec)
        return True

    async def decline_signer(self, guild: discord.Guild, filing_id: str, role: str, signer_id: int) -> bool:
        """Mark a handoff role as declined; staff can reassign it via the Assign button."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] != "pending":
            return False
        signer_state = record.get("signers", {}).get(role)
        if not signer_state or signer_state["status"] != "pending" or signer_state["user_id"] != signer_id:
            return False

        signer_state["status"] = "declined"
        published[filing_id] = record
        await guild_conf.published_documents.set(published)

        spec = self.templates.get(record["template_id"])
        await self._refresh_review_message(guild, record, spec)

        channel = await self._get_channel(record.get("channel_id"))
        if channel and spec:
            signer_spec = next((s for s in spec.get("signers", []) if s["role"] == role), None)
            label = signer_spec["label"] if signer_spec else role
            await channel.send(f"⚠️ **{label}** declined to sign. Staff can reassign via the Assign button.")
        return True

    async def approve(
        self,
        guild: discord.Guild,
        filing_id: str,
        approver: discord.Member,
        judge_answers: dict[str, str],
    ) -> bool:
        """Collect judge/approval-time fields, render the final document, and file it (not public yet)."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] != "pending":
            return False

        spec = self.templates.get(record["template_id"])
        if not spec:
            return False

        signers_state = record.get("signers", {})
        if any(s["status"] != "signed" for s in signers_state.values()):
            return False

        full_answers = dict(record["answers"])
        full_answers.update(judge_answers)
        for field in self.templates.auto_fields(spec, "approval"):
            full_answers[field["key"]] = _today()

        rendered = self.templates.render(record["template_id"], full_answers)
        html_path = self.templates.save_document(record["template_id"], filing_id, rendered)

        name_field = next((f for f in judge_answers if f.endswith("name")), None)
        signed_by = judge_answers.get(name_field) if name_field else approver.display_name

        sidecar = {
            "filing_id": filing_id,
            "template_id": record["template_id"],
            "title": record["title"],
            "category": record["category"],
            "html_file": f"{record['template_id']}/{filing_id}.html",
            "filed_date": record["filed_date"],
            "signed_date": _today(),
            "signed_by": signed_by,
            "index_values": {k: full_answers.get(k, "") for k in spec.get("index_fields", [])},
        }
        json_path = self.templates.save_sidecar(record["template_id"], filing_id, sidecar)

        record["status"] = "approved"
        record["answers"] = full_answers
        record["approved_by"] = approver.id
        record["signed_date"] = sidecar["signed_date"]
        record["signed_by"] = signed_by
        record["html_path"] = str(html_path)
        record["json_path"] = str(json_path)
        published[filing_id] = record
        await guild_conf.published_documents.set(published)
        return True

    async def deny(self, guild: discord.Guild, filing_id: str) -> bool:
        """Deny a pending filing, notify the filer, disable any outstanding signer DMs,
        and archive+close the review channel — a denied filing never goes through
        make_public, so this is its only path to getting cleaned up at all."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] != "pending":
            return False
        record["status"] = "denied"
        published[filing_id] = record
        await guild_conf.published_documents.set(published)

        user = self.bot.get_user(record["user_id"])
        if user:
            try:
                await user.send(f"❌ Your **{record['title']}** filing was denied by staff.")
            except discord.Forbidden:
                pass

        for signer_state in record.get("signers", {}).values():
            if signer_state.get("status") != "pending":
                continue
            dm_message_id = signer_state.get("dm_message_id")
            signer_user_id = signer_state.get("user_id")
            if not dm_message_id or not signer_user_id:
                continue
            signer_user = self.bot.get_user(signer_user_id)
            if not signer_user:
                continue
            try:
                dm = await signer_user.create_dm()
                msg = await dm.fetch_message(dm_message_id)
                await msg.edit(content=msg.content + "\n\n❌ This filing was denied by staff — no action needed.", view=None)
            except discord.HTTPException:
                pass

        await self._close_channel(guild, filing_id, f"❌ **{record['title']}** — denied")
        return True

    async def make_public(self, guild: discord.Guild, filing_id: str) -> str | None:
        """Publish an approved, on-file document to the public site."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] != "approved":
            return None

        html_path = self.templates.documents_path / record["template_id"] / f"{filing_id}.html"
        json_path = self.templates.documents_path / record["template_id"] / f"{filing_id}.json"
        url = await self.publisher.publish(html_path, json_path, record["template_id"], filing_id)

        record["status"] = "published"
        record["published_url"] = url
        published[filing_id] = record
        await guild_conf.published_documents.set(published)

        channel = await self._get_channel(record.get("channel_id"))
        if channel is not None:
            if url:
                await channel.send(
                    f"🌐 **{record['title']}** is on file and will be public shortly. This "
                    "channel will be archived to the review log and closed in a couple minutes."
                )
            else:
                await channel.send(
                    f"📄 **{record['title']}** approved and on file (site publishing isn't wired up "
                    "yet, so it isn't live). This channel will be archived to the review log and "
                    "closed in a couple minutes.",
                    file=discord.File(str(html_path)),
                )
            # Give the site's GitHub Action time to rebuild before announcing the live
            # link and archiving — don't block the caller (staff already got their own
            # confirmation) waiting on this.
            self.bot.loop.create_task(self._announce_and_close(guild, filing_id, url))
        return url

    async def _announce_and_close(self, guild: discord.Guild, filing_id: str, url: str | None) -> None:
        """After the publish-delay window: announce the live link in the channel, DM
        it to the filer directly too (so they have it even if they never revisit the
        channel), then hand off to `_close_channel` for the actual archive+delete.
        """
        await asyncio.sleep(PUBLISH_ANNOUNCE_DELAY_SECONDS)

        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record:
            return  # purged/deleted in the meantime
        channel = await self._get_channel(record.get("channel_id"))
        if channel is None:
            return

        if url:
            try:
                await channel.send(f"📄 **{record['title']}** is now public — {url}")
            except discord.HTTPException:
                pass
            filer = self.bot.get_user(record["user_id"])
            if filer:
                try:
                    await filer.send(f"📄 Your **{record['title']}** filing is now public — {url}")
                except discord.Forbidden:
                    pass

        summary_line = f"📄 **{record['title']}**\n{url}" if url else f"📄 **{record['title']}** (not published live)"
        await self._close_channel(guild, filing_id, summary_line)

    async def _close_channel(self, guild: discord.Guild, filing_id: str, summary_line: str) -> None:
        """Archive a filing's review channel to the configured log forum under
        `summary_line` (a document link for a published filing, a plain denial note
        otherwise), then delete the channel — the one path both `make_public` (via
        `_announce_and_close`) and `deny` funnel through, so a filing gets the same
        cleanup regardless of which way it ends.

        Archiving is entirely optional (`document_log_forum` unset by default) and
        only deletes the channel if the archive actually succeeds — if it's not
        configured, or the archive step raises partway through, the channel is left
        exactly as it would have been before this feature existed rather than
        risking losing it.
        """
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record:
            return
        channel = await self._get_channel(record.get("channel_id"))
        if channel is None:
            return

        log_forum_id = await guild_conf.document_log_forum()
        log_forum = guild.get_channel(log_forum_id) if log_forum_id else None
        if not log_forum or not isinstance(log_forum, discord.ForumChannel):
            return

        try:
            await self._archive_to_log(log_forum, record, channel, summary_line)
        except discord.HTTPException:
            return  # best-effort archival; don't delete a channel we failed to archive

        published[filing_id] = record  # _archive_to_log set record["archived_thread_id"]
        await guild_conf.published_documents.set(published)

        try:
            await channel.delete(reason=f"Filecab: filing {filing_id} closed")
        except discord.HTTPException:
            pass

    async def _archive_to_log(
        self, log_forum: discord.ForumChannel, record: dict, channel: discord.TextChannel, summary_line: str
    ) -> None:
        """Post a filing's full channel history to the log forum, tagged by category,
        then lock and archive that forum post. Message 1 is `summary_line`; message 2
        is the transcript, as text if it fits or a .txt attachment if not (a real
        channel's history can exceed Discord's 2000-char message limit). Any
        attachments posted in the channel are downloaded and re-uploaded, since
        they'd otherwise be lost when the channel is deleted.
        """
        messages = [m async for m in channel.history(limit=None, oldest_first=True)]
        transcript_text = build_channel_transcript(messages)

        saved_attachments: list[tuple[str, bytes]] = []
        for msg in messages:
            for att in msg.attachments:
                try:
                    saved_attachments.append((att.filename, await att.read()))
                except discord.HTTPException:
                    pass

        tags = []
        category_name = record.get("category")
        if category_name:
            tag = await get_or_create_forum_tag(log_forum, category_name[:20])
            if tag:
                tags = [tag]

        thread, _first_msg = await log_forum.create_thread(
            name=f"{record['title']} — {record['filing_id']}"[:100],
            content=summary_line,
            applied_tags=tags,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        record["archived_thread_id"] = thread.id

        body = transcript_text[:2000] if transcript_text else "(no messages)"
        await thread.send(content=body, allowed_mentions=discord.AllowedMentions.none())
        if len(transcript_text) > 2000:
            fp = io.BytesIO(transcript_text.encode("utf-8"))
            await thread.send(
                content="Full transcript attached:",
                file=discord.File(fp, filename=f"{record['filing_id']}.txt"),
            )
        if saved_attachments:
            for i in range(0, len(saved_attachments), 10):
                batch = saved_attachments[i : i + 10]
                await thread.send(
                    content="📎 Attachments:" if i == 0 else None,
                    files=[discord.File(io.BytesIO(data), filename=name) for name, data in batch],
                )
        await thread.edit(archived=True, locked=True)

    async def takedown(self, guild: discord.Guild, filing_id: str) -> bool:
        """Remove a filed document: delete the local files and call unpublish (stub) if it was live."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] not in ("approved", "published"):
            return False

        html_path = self.templates.documents_path / record["template_id"] / f"{filing_id}.html"
        json_path = self.templates.documents_path / record["template_id"] / f"{filing_id}.json"
        for path in (html_path, json_path):
            if path.exists():
                path.unlink()

        if record["status"] == "published":
            await self.publisher.unpublish(record["template_id"], filing_id)

        record["status"] = "removed"
        published[filing_id] = record
        await guild_conf.published_documents.set(published)
        return True

    async def wipe_guild_data(self, guild: discord.Guild) -> dict:
        """Permanently erase every filing this guild has produced — local document
        files, published GitHub files, review-category channels, log-forum threads,
        and filing records — plus the bot-wide filing ID counter. Used only by the
        owner-gated `filecab nuke` command to reset a test server to a clean slate.
        Templates and all other guild config (channels, roles, site repo) are left
        untouched.

        Deletes every channel actually found in the review category (not just ones
        with a tracked record) and every thread actually found in the log forum,
        since orphaned test channels/threads with no matching record are exactly
        the kind of leftover this is meant to clear.
        """
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()

        summary = {
            "records": len(published),
            "local_files": 0,
            "github_files": 0,
            "channels_deleted": 0,
            "channels_failed": 0,
            "threads_deleted": 0,
            "threads_failed": 0,
        }

        for filing_id, record in published.items():
            template_id = record.get("template_id")
            if not template_id:
                continue
            for path in (
                self.templates.documents_path / template_id / f"{filing_id}.html",
                self.templates.documents_path / template_id / f"{filing_id}.json",
            ):
                if path.exists():
                    path.unlink()
                    summary["local_files"] += 1
            if record.get("status") == "published":
                if await self.publisher.unpublish(template_id, filing_id):
                    summary["github_files"] += 1

        await guild_conf.published_documents.set({})

        category_id = await guild_conf.document_review_category()
        category = guild.get_channel(category_id) if category_id else None
        if isinstance(category, discord.CategoryChannel):
            for channel in list(category.channels):
                try:
                    await channel.delete(reason="Filecab: nuke — clearing test data")
                    summary["channels_deleted"] += 1
                except discord.HTTPException:
                    summary["channels_failed"] += 1

        log_forum_id = await guild_conf.document_log_forum()
        log_forum = guild.get_channel(log_forum_id) if log_forum_id else None
        if isinstance(log_forum, discord.ForumChannel):
            threads = list(log_forum.threads)
            try:
                async for thread in log_forum.archived_threads(limit=None):
                    threads.append(thread)
            except discord.HTTPException:
                pass
            for thread in threads:
                try:
                    await thread.delete()
                    summary["threads_deleted"] += 1
                except discord.HTTPException:
                    summary["threads_failed"] += 1

        await self.config.filing_counters.set({})
        return summary

    async def purge(self, guild: discord.Guild, filing_id: str) -> bool:
        """Permanently erase a filing: unpublish/delete files if still on file, then drop its record.

        Unlike `takedown`, this removes the stored answers entirely rather
        than leaving a `status: "removed"` record behind. Pending filings
        aren't eligible — deny it first (or let it run its course) so an
        open review channel never loses the record it's referencing.
        """
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(filing_id)
        if not record or record["status"] == "pending":
            return False

        if record["status"] in ("approved", "published"):
            await self.takedown(guild, filing_id)
            published = await guild_conf.published_documents()

        del published[filing_id]
        await guild_conf.published_documents.set(published)
        return True
