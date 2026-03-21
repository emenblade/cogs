"""Application builder, DM Q&A flow, and review logic."""
from __future__ import annotations
import asyncio
import json
import re
import discord
from redbot.core import Config
from redbot.core.bot import Red
from pathlib import Path


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
                "(You can add up to 50 questions.)"
            )
        except discord.Forbidden:
            return

        questions = await self._run_question_builder(member, dm)

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
            await dm.send(
                f"✅ Question {len(questions)} saved.\n\n"
                f"What is **question {len(questions)+1}**? "
                f"({remaining} remaining, reply `done` when finished.)"
            )

        return questions

    async def assign_application(
        self,
        guild: discord.Guild,
        slug: str,
        name: str,
        description: str,
        channel: discord.TextChannel,
        approval_role_id: int,
        cooldown_days: int,
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
            "cooldown_days": cooldown_days,
            "active_reviews": {},
        }
        await guild_conf.application_assignments.set(assignments)
        return msg
