"""DM Q&A filing flow, review-forum posting, and publish finalization."""
from __future__ import annotations
import io
import time
import discord
from redbot.core import Config
from redbot.core.bot import Red
from .template_manager import TemplateManager
from .publisher import DocumentPublisher


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
        self, user: discord.User, guild: discord.Guild, slug: str, dm: discord.DMChannel
    ) -> None:
        """Set active_filing state and send the first field's prompt via DM."""
        spec = self.templates.get(slug)
        if not spec:
            await dm.send("❌ This document type is no longer available. Please contact staff.")
            return

        state = {"slug": slug, "guild_id": guild.id, "field_index": 0, "answers": {}}
        await self.config.user(user).active_filing.set(state)

        fields = spec["fields"]
        await dm.send(
            f"👋 Let's file a **{spec.get('name', slug)}**! ({len(fields)} question(s))\n"
            f"*Reply `cancel` at any time to cancel this filing.*\n\n"
            f"**Question 1 of {len(fields)}:** {fields[0]['prompt']}"
        )

    async def handle_reply(
        self,
        member: discord.Member,
        guild: discord.Guild,
        state: dict,
        message: discord.Message,
    ) -> None:
        """Process one DM reply, save the answer, and advance or finish the filing."""
        spec = self.templates.get(state["slug"])
        if not spec:
            await self.config.user(member).active_filing.set(None)
            await message.channel.send(
                "❌ This document type was removed before you finished. Filing cancelled."
            )
            return

        fields = spec["fields"]
        answer = message.content.strip()

        if answer.lower() == "cancel":
            await self.config.user(member).active_filing.set(None)
            await message.channel.send(
                "❌ Filing cancelled. You can start again any time from the document panel."
            )
            return

        current_field = fields[state["field_index"]]
        new_state = {
            **state,
            "field_index": state["field_index"] + 1,
            "answers": {**state["answers"], current_field["key"]: answer},
        }

        if new_state["field_index"] >= len(fields):
            await self.config.user(member).active_filing.set(None)
            await message.channel.send("✅ **Filing complete!** Your document is being processed.")
            await self._submit(member, guild, spec, new_state["answers"])
        else:
            await self.config.user(member).active_filing.set(new_state)
            next_field = fields[new_state["field_index"]]
            await message.channel.send(
                f"**Question {new_state['field_index'] + 1} of {len(fields)}:** {next_field['prompt']}"
            )

    async def _submit(
        self, member: discord.Member, guild: discord.Guild, spec: dict, answers: dict[str, str]
    ) -> None:
        """Render the document, save it locally, and either route to review or finalize."""
        slug = spec["_slug"]
        output_dir = spec.get("output_dir", slug)
        ts = int(time.time())
        filename = f"{slug}-{member.id}-{ts}.html"
        doc_id = f"{slug}-{member.id}-{ts}"

        rendered = self.templates.render(slug, answers)
        path = self.templates.save_document(slug, filename, rendered)

        guild_conf = self.config.guild(guild)
        approval_required = await guild_conf.approval_required()
        record = {
            "slug": slug,
            "output_dir": output_dir,
            "filename": filename,
            "user_id": member.id,
            "status": "pending" if approval_required else "published",
        }

        if approval_required:
            await self._post_review(member, guild, spec, answers, doc_id, record, path)
        else:
            await self._finalize(guild, doc_id, record, path)

    async def _post_review(
        self,
        member: discord.Member,
        guild: discord.Guild,
        spec: dict,
        answers: dict[str, str],
        doc_id: str,
        record: dict,
        path,
    ) -> None:
        """Post a Q&A transcript + Approve/Deny view to the review forum."""
        from .views import FilingReviewView

        guild_conf = self.config.guild(guild)
        forum_id = await guild_conf.document_review_forum()
        forum = guild.get_channel(forum_id) if forum_id else None
        if not forum or not isinstance(forum, discord.ForumChannel):
            # No review forum configured — fall back to publishing directly.
            record["status"] = "published"
            await self._finalize(guild, doc_id, record, path)
            return

        name = spec.get("name", spec["_slug"])
        lines = [f"**Document: {name}**", f"Filed by: {member.mention} ({member.name})", ""]
        for field in spec["fields"]:
            lines.append(f"**{field['prompt']}**")
            lines.append(answers.get(field["key"], ""))
            lines.append("")
        transcript = "\n".join(lines)

        view = FilingReviewView(self.config, self.bot, doc_id)
        suffix = "\n…(see attachment)"
        content = transcript if len(transcript) <= 2000 else transcript[:2000 - len(suffix)] + suffix
        thread, first_msg = await forum.create_thread(
            name=f"{name} — {member.name}",
            content=content,
            view=view,
        )
        if len(transcript) > 2000:
            fp = io.BytesIO(transcript.encode("utf-8"))
            await thread.send(file=discord.File(fp, filename=f"{doc_id}.txt"))

        record["thread_id"] = thread.id
        record["message_id"] = first_msg.id
        published = await guild_conf.published_documents()
        published[doc_id] = record
        await guild_conf.published_documents.set(published)

    async def _finalize(self, guild: discord.Guild, doc_id: str, record: dict, path) -> None:
        """Publish the document (stubbed) and post the result to the document channel."""
        guild_conf = self.config.guild(guild)
        url = await self.publisher.publish(path, record["output_dir"])
        record["status"] = "published"

        published = await guild_conf.published_documents()
        published[doc_id] = record
        await guild_conf.published_documents.set(published)

        channel_id = await guild_conf.document_channel()
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            return

        if url:
            await channel.send(f"📄 New document filed: **{record['slug']}** — {url}")
        else:
            await channel.send(
                f"📄 New document filed: **{record['slug']}** (site publishing isn't configured "
                "yet — file saved locally).",
                file=discord.File(str(path)),
            )

    async def approve(self, guild: discord.Guild, doc_id: str) -> None:
        """Approve a pending filing and finalize/publish it."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(doc_id)
        if not record or record["status"] != "pending":
            return
        path = self.templates.documents_path / record["output_dir"] / record["filename"]
        await self._finalize(guild, doc_id, record, path)

    async def deny(self, guild: discord.Guild, doc_id: str) -> None:
        """Deny a pending filing: delete the local file and notify the filer."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(doc_id)
        if not record:
            return
        path = self.templates.documents_path / record["output_dir"] / record["filename"]
        if path.exists():
            path.unlink()
        record["status"] = "denied"
        published[doc_id] = record
        await guild_conf.published_documents.set(published)

        user = self.bot.get_user(record["user_id"])
        if user:
            try:
                await user.send(f"❌ Your **{record['slug']}** filing was denied by staff.")
            except discord.Forbidden:
                pass

    async def takedown(self, guild: discord.Guild, doc_id: str) -> bool:
        """Remove a published document: delete the local file and call unpublish (stub)."""
        guild_conf = self.config.guild(guild)
        published = await guild_conf.published_documents()
        record = published.get(doc_id)
        if not record:
            return False
        path = self.templates.documents_path / record["output_dir"] / record["filename"]
        if path.exists():
            path.unlink()
        await self.publisher.unpublish(record["output_dir"], record["filename"])
        record["status"] = "removed"
        published[doc_id] = record
        await guild_conf.published_documents.set(published)
        return True
