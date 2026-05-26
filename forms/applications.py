"""Application builder, DM Q&A flow, and review logic."""
from __future__ import annotations
import asyncio
import json
import re
import discord
from redbot.core import Config
from redbot.core.bot import Red
from pathlib import Path
from .utils import parse_question, get_or_create_forum_tag


_MIN_RULE_HINT = (
    "💡 *Optional:* append `[min:50]` for a 50-character minimum or `[min:3w]` for a 3-word minimum "
    "— e.g. `Describe your experience. [min:100]` — leave it out if you don't need one."
)


class ApplicationManager:
    def __init__(self, bot: Red, config: Config, data_path: Path) -> None:
        self.bot = bot
        self.config = config
        self.data_path = data_path
        self._app_path = data_path / "applications"

    def initialize(self) -> None:
        """Create required data directories. Call after construction."""
        self._app_path.mkdir(parents=True, exist_ok=True)

    async def _save_application(self, data: dict) -> None:
        slug = data["slug"]
        path = self._app_path / f"{slug}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    async def load_applications(self) -> dict[str, dict]:
        """Return all saved application templates keyed by slug."""
        apps = {}
        for path in self._app_path.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                apps[data["slug"]] = data
            except (json.JSONDecodeError, KeyError):
                pass
        return apps

    async def delete_application(self, slug: str) -> bool:
        """Delete an application template. Returns True if deleted."""
        path = self._app_path / f"{slug}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    async def create_application(
        self, member: discord.Member, name: str, description: str
    ) -> None:
        """Start the DM question builder for a new application."""
        slug = re.sub(r"[^a-z0-9\-]", "", name.lower().replace(" ", "-"))

        try:
            dm = await member.create_dm()
            await dm.send(
                f"👋 Let's build **{name}**!\n\n"
                "What is **question 1**? Reply `done` at any time when you're finished. "
                f"(You can add up to 50 questions.)\n\n{_MIN_RULE_HINT}"
            )
        except discord.Forbidden:
            return

        questions = await self._run_question_builder(member, dm)

        if not questions:
            await dm.send("❌ No questions were added — application was not saved.")
            return

        data = {
            "name": name,
            "slug": slug,
            "description": description,
            "questions": questions,
        }
        await self._save_application(data)

        summary = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
        await dm.send(
            f"✅ **{name}** saved with {len(questions)} question(s):\n\n{summary}"
        )

    async def _run_question_builder(
        self, member: discord.Member, dm: discord.DMChannel
    ) -> list[str]:
        """Interactively collect questions from a staff member via DM."""
        questions = []

        def check(m: discord.Message) -> bool:
            return m.author.id == member.id and m.channel.id == dm.id

        while len(questions) < 50:
            try:
                reply = await self.bot.wait_for("message", check=check, timeout=600)
            except asyncio.TimeoutError:
                await dm.send("⏰ Session timed out. Progress saved so far.")
                break

            if reply.content.strip().lower() == "done":
                break

            questions.append(reply.content.strip())
            remaining = 50 - len(questions)
            if remaining > 0:
                await dm.send(
                    f"✅ Question {len(questions)} saved.\n\n"
                    f"What is **question {len(questions)+1}**? "
                    f"({remaining} remaining, reply `done` when finished.)\n\n{_MIN_RULE_HINT}"
                )
            else:
                await dm.send(
                    f"✅ Question {len(questions)} saved. You've reached the 50-question limit."
                )

        return questions

    async def _run_edit_question_builder(
        self, member: discord.Member, dm: discord.DMChannel, existing_questions: list[str]
    ) -> list[str]:
        """Walk through existing questions, letting staff keep or replace each."""
        updated = []

        def check(m):
            return m.author.id == member.id and m.channel.id == dm.id

        for i, q in enumerate(existing_questions):
            display_q, rule = parse_question(q)
            rule_note = ""
            if rule:
                rule_note = (
                    f"\n*Current rule:* minimum **{rule['min']} {rule['type']}**"
                )
            await dm.send(
                f"**Question {i+1} is currently:**\n> {display_q}{rule_note}\n\n"
                f"Reply with new text to replace it, reply `keep` to leave it unchanged, "
                f"or reply `delete` to remove it.\n\n{_MIN_RULE_HINT}"
            )
            try:
                reply = await self.bot.wait_for("message", check=check, timeout=300)
            except asyncio.TimeoutError:
                await dm.send("⏰ Timed out. Keeping remaining questions as-is.")
                updated.extend(existing_questions[i:])
                return updated

            cmd = reply.content.strip().lower()
            if cmd == "keep":
                updated.append(q)
                await dm.send(f"✅ Question {i+1} kept.")
            elif cmd == "delete":
                await dm.send(f"🗑️ Question {i+1} deleted.")
            else:
                updated.append(reply.content.strip())
                await dm.send(f"✅ Question {i+1} updated.")

        # Ask if they want to add more
        await dm.send(
            f"All {len(existing_questions)} questions reviewed. "
            "Do you want to add more questions? Reply `yes` or `no`."
        )
        try:
            reply = await self.bot.wait_for("message", check=check, timeout=120)
            if reply.content.strip().lower() == "yes":
                extra = await self._run_question_builder(member, dm)
                updated.extend(extra)
        except asyncio.TimeoutError:
            pass

        return updated

    async def edit_application(
        self, member: discord.Member, slug: str,
        new_name: str | None = None, new_description: str | None = None
    ) -> bool:
        """Edit an existing application. Returns False if not found."""
        apps = await self.load_applications()
        if slug not in apps:
            return False

        app = apps[slug]
        if new_name:
            app["name"] = new_name
        if new_description:
            app["description"] = new_description

        try:
            dm = await member.create_dm()
            updated_questions = await self._run_edit_question_builder(member, dm, app["questions"])
            app["questions"] = updated_questions
            await self._save_application(app)
            await dm.send(f"✅ **{app['name']}** has been updated with {len(updated_questions)} question(s).")
            return True
        except discord.Forbidden:
            return False

    async def assign_application(
        self,
        guild: discord.Guild,
        slug: str,
        name: str,
        description: str,
        channel: discord.TextChannel,
        approval_role_id: int,
        removal_role_id: int | None = None,
        required_role_id: int | None = None,
        review_forum_id: int | None = None,
        reviewer_role_ids: list[int] | None = None,
    ) -> discord.Message:
        """Post the application embed in a channel and save the assignment to config."""
        from .views import ApplyView

        embed = discord.Embed(
            title=f"📋 {name}",
            description=description,
            color=discord.Color.green(),
        )
        embed.set_footer(text="Click Apply to begin. Staff will review your answers.")
        view = ApplyView(self.config, self.bot, slug)
        msg = await channel.send(embed=embed, view=view)

        guild_conf = self.config.guild(guild)
        assignments = await guild_conf.application_assignments()
        assignments[slug] = {
            "channel_id": channel.id,
            "panel_message_id": msg.id,
            "approval_role_id": approval_role_id,
            "removal_role_id": removal_role_id,
            "required_role_id": required_role_id,
            "review_forum_id": review_forum_id,
            "reviewer_role_ids": reviewer_role_ids or [],
            "active_reviews": {},
        }
        await guild_conf.application_assignments.set(assignments)
        return msg

    async def start_application(
        self,
        user: discord.User,
        guild: discord.Guild,
        slug: str,
        dm: discord.DMChannel,
    ) -> None:
        """Set active_application state and send question 1 via DM."""
        apps = await self.load_applications()
        app = apps.get(slug)
        if not app:
            await dm.send("❌ This application no longer exists. Please contact staff.")
            return

        state = {
            "slug": slug,
            "guild_id": guild.id,
            "question_index": 0,
            "answers": [],
        }
        await self.config.user(user).active_application.set(state)

        total = len(app["questions"])
        first_q, _ = parse_question(app["questions"][0])
        await dm.send(
            f"👋 Welcome to the **{app['name']}** application! ({total} question(s))\n"
            f"*Reply `cancel` at any time to cancel your application.*\n\n"
            f"**Question 1 of {total}:** {first_q}"
        )

    async def _handle_application_reply(
        self,
        member: discord.Member,
        guild: discord.Guild,
        state: dict,
        message: discord.Message,
    ) -> None:
        """Process one DM reply, save the answer, and advance the application."""
        apps = await self.load_applications()
        app = apps.get(state["slug"])
        if not app:
            return

        questions = app["questions"]
        total = len(questions)
        answer = message.content.strip()

        if answer.lower() == "cancel":
            await self.config.user(member).active_application.set(None)
            await message.channel.send(
                "❌ Application cancelled. You can start again any time by clicking Apply."
            )
            return

        # Validate minimum length rule if one is set on this question
        current_q = questions[state["question_index"]]
        _, rule = parse_question(current_q)
        if rule:
            if rule["type"] == "chars":
                count = len(answer)
                if count < rule["min"]:
                    await message.channel.send(
                        f"⚠️ Your answer is too short ({count} character{'s' if count != 1 else ''}). "
                        f"This question requires at least **{rule['min']} characters**. Please try again."
                    )
                    return
            elif rule["type"] == "words":
                count = len(answer.split())
                if count < rule["min"]:
                    await message.channel.send(
                        f"⚠️ Your answer is too short ({count} word{'s' if count != 1 else ''}). "
                        f"This question requires at least **{rule['min']} words**. Please try again."
                    )
                    return

        new_state = {
            **state,
            "question_index": state["question_index"] + 1,
            "answers": state["answers"] + [answer],
        }

        if new_state["question_index"] >= total:
            # All questions answered — submit
            await self.config.user(member).active_application.set(None)
            await message.channel.send(
                "✅ **Application submitted!** Staff will review your answers within 5 days. "
                "We'll DM you with their decision. Thank you!"
            )
            await self._post_review_forum(member, guild, app, new_state["answers"])
        else:
            # Save progress and send next question
            await self.config.user(member).active_application.set(new_state)
            next_display, _ = parse_question(questions[new_state["question_index"]])
            await message.channel.send(
                f"**Question {new_state['question_index'] + 1} of {total}:** {next_display}"
            )

    async def _post_review_forum(
        self,
        user: discord.User,
        guild: discord.Guild,
        app: dict,
        answers: list[str],
    ) -> None:
        """Create a staff forum review thread with Approve/Deny buttons."""
        import io
        from .views import ReviewView

        guild_conf = self.config.guild(guild)
        assignments = await guild_conf.application_assignments()
        forum_id = assignments.get(app["slug"], {}).get("review_forum_id")

        forum = guild.get_channel(forum_id) if forum_id else None
        if not forum or not isinstance(forum, discord.ForumChannel):
            return

        # Build Q&A transcript
        lines = [f"**Application: {app['name']}**", f"Applicant: {user.mention} ({user.name})", ""]
        for i, (q, a) in enumerate(zip(app["questions"], answers), 1):
            display_q, _ = parse_question(q)
            lines.append(f"**Q{i}: {display_q}**")
            lines.append(f"A: {a}")
            lines.append("")
        transcript = "\n".join(lines)

        needs_review_tag = await get_or_create_forum_tag(forum, "Needs Review")
        tags = [needs_review_tag] if needs_review_tag else []
        view = ReviewView(self.config, self.bot, app["slug"], user.id, guild.id)

        suffix = "\n…(see attachment)"
        content = transcript if len(transcript) <= 2000 else transcript[:2000 - len(suffix)] + suffix
        thread, first_msg = await forum.create_thread(
            name=f"{app['name']} — {user.name}",
            content=content,
            applied_tags=tags,
            view=view,
        )

        # If transcript too long, attach full file
        if len(transcript) > 2000:
            fp = io.BytesIO(transcript.encode("utf-8"))
            await thread.send(file=discord.File(fp, filename=f"{app['slug']}-{user.name}.txt"))

        # Ping reviewer roles so staff are notified
        reviewer_role_ids = assignments.get(app["slug"], {}).get("reviewer_role_ids", [])
        if reviewer_role_ids:
            mentions = " ".join(f"<@&{rid}>" for rid in reviewer_role_ids)
            await thread.send(content=mentions)

        # Store for restart recovery
        assignments = await guild_conf.application_assignments()
        if app["slug"] in assignments:
            assignments[app["slug"]]["active_reviews"][str(user.id)] = {
                "thread_id": thread.id,
                "review_message_id": first_msg.id,
            }
            await guild_conf.application_assignments.set(assignments)
