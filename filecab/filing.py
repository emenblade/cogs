"""DM Q&A filing flow, multi-signer handoff, approval, and publish/takedown."""
from __future__ import annotations
import io
from datetime import date, datetime
import discord
from redbot.core import Config
from redbot.core.bot import Red
from .template_manager import TemplateManager
from .publisher import DocumentPublisher


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
        """Set active_filing state and send the first field's prompt via DM."""
        spec = self.templates.get(template_id)
        if not spec:
            await dm.send("❌ This document type is no longer available. Please contact staff.")
            return

        prompted = self.templates.prompted_fields(spec)
        state = {"template_id": template_id, "guild_id": guild.id, "field_index": 0, "answers": {}}
        await self.config.user(user).active_filing.set(state)

        await dm.send(
            f"👋 Let's file a **{spec['title']}**! ({len(prompted)} question(s))\n"
            f"*Reply `cancel` at any time to cancel this filing.*\n\n"
            f"**Question 1 of {len(prompted)}:** {prompted[0]['prompt']}"
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
        new_state = {
            **state,
            "field_index": state["field_index"] + 1,
            "answers": {**state["answers"], current_field["key"]: answer},
        }

        if new_state["field_index"] >= len(prompted):
            await self.config.user(member).active_filing.set(None)
            await message.channel.send("✅ **Filing complete!** Your document has been sent for staff review.")
            await self._submit(member, guild, spec, new_state["answers"])
        else:
            await self.config.user(member).active_filing.set(new_state)
            next_field = prompted[new_state["field_index"]]
            await message.channel.send(
                f"**Question {new_state['field_index'] + 1} of {len(prompted)}:** {next_field['prompt']}"
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
        """Post a Q&A transcript + Approve/Deny/Assign view to the review forum."""
        from .views import FilingReviewView

        guild_conf = self.config.guild(guild)
        forum_id = await guild_conf.document_review_forum()
        forum = guild.get_channel(forum_id) if forum_id else None
        if not forum or not isinstance(forum, discord.ForumChannel):
            await member.send(
                "⚠️ Your filing was completed but staff haven't configured a review forum yet — "
                "please let them know so it can be processed."
            )
            return

        record["signers"] = {
            s["role"]: {"user_id": None, "status": "unassigned", "dm_message_id": None}
            for s in self.templates.handoff_signers(spec)
        }

        transcript = self._build_transcript(spec, f"{member.mention} ({member.name})", record["answers"])
        content, overflowed = _truncate_for_discord(transcript)
        view = FilingReviewView(self.config, self.bot, filing_id, spec, record["signers"])
        thread, first_msg = await forum.create_thread(
            name=f"{spec['title']} — {member.name}",
            content=content,
            view=view,
        )
        if overflowed:
            fp = io.BytesIO(transcript.encode("utf-8"))
            await thread.send(file=discord.File(fp, filename=f"{filing_id}.txt"))

        record["thread_id"] = thread.id
        record["message_id"] = first_msg.id
        published = await guild_conf.published_documents()
        published[filing_id] = record
        await guild_conf.published_documents.set(published)

    async def _refresh_review_message(self, guild: discord.Guild, record: dict, spec: dict) -> None:
        """Re-render the review-forum message's view to reflect current signer state."""
        from .views import FilingReviewView

        thread_id = record.get("thread_id")
        message_id = record.get("message_id")
        if not thread_id or not message_id:
            return
        thread = self.bot.get_channel(thread_id)
        if thread is None:
            try:
                thread = await self.bot.fetch_channel(thread_id)
            except discord.HTTPException:
                return
        try:
            message = await thread.fetch_message(message_id)
        except discord.HTTPException:
            return
        view = FilingReviewView(self.config, self.bot, record["filing_id"], spec, record.get("signers", {}))
        await message.edit(view=view)

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
            dm_msg = await dm.send(
                f"You've been asked to sign as **{signer_spec['label']}** on a "
                f"**{spec['title']}**, filed by {filer_label}.\n\n{content}",
                view=SignerRequestView(filing_id, role, guild.id),
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

        thread_id = record.get("thread_id")
        thread = self.bot.get_channel(thread_id) if thread_id else None
        if thread and spec:
            signer_spec = next((s for s in spec.get("signers", []) if s["role"] == role), None)
            label = signer_spec["label"] if signer_spec else role
            await thread.send(f"⚠️ **{label}** declined to sign. Staff can reassign via the Assign button.")
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
        """Deny a pending filing, notify the filer, and disable any outstanding signer DMs."""
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
        return True

    async def make_public(self, guild: discord.Guild, filing_id: str) -> str | None:
        """Publish an approved, on-file document to the public site (stubbed)."""
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

        channel_id = await guild_conf.document_channel()
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is not None:
            if url:
                await channel.send(f"📄 **{record['title']}** is now public — {url}")
            else:
                await channel.send(
                    f"📄 **{record['title']}** approved and on file (site publishing isn't wired up "
                    "yet, so it isn't live).",
                    file=discord.File(str(html_path)),
                )
        return url

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
