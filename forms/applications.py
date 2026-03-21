"""Application builder, DM Q&A flow, and review logic."""
from __future__ import annotations
import json
import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from pathlib import Path


class ApplicationManager:
    def __init__(self, bot: Red, config: Config, data_path: Path) -> None:
        self.bot = bot
        self.config = config
        self.data_path = data_path
        self._app_path = data_path / "applications"
        self._app_path.mkdir(parents=True, exist_ok=True)
