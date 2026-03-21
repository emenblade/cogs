"""
Root conftest.py — mocks redbot.core for testing on Python 3.14
where Red-DiscordBot cannot be installed. The real redbot package
is only needed on the deployment server running the bot.
"""
import sys
from unittest.mock import MagicMock, AsyncMock
import types


def _build_redbot_stub():
    """Build a minimal stub of redbot.core for import-time compatibility."""

    # --- redbot.core.commands ---
    commands_mod = types.ModuleType("redbot.core.commands")

    class CogMeta(type):
        pass

    class Cog(metaclass=CogMeta):
        @staticmethod
        def listener(func=None):
            if func is not None:
                return func
            def decorator(f):
                return f
            return decorator

    def command(**kwargs):
        def decorator(func):
            func._is_command = True
            func._kwargs = kwargs
            return func
        return decorator

    def group(**kwargs):
        def decorator(func):
            func._is_group = True
            func._kwargs = kwargs

            def sub_command(**kw):
                def inner(f):
                    f._is_command = True
                    return f
                return inner
            func.command = sub_command
            return func
        return decorator

    def guild_only():
        def decorator(func):
            return func
        return decorator

    def admin_or_permissions(**kwargs):
        def decorator(func):
            return func
        return decorator

    class Context:
        pass

    commands_mod.Cog = Cog
    commands_mod.command = command
    commands_mod.group = group
    commands_mod.guild_only = guild_only
    commands_mod.admin_or_permissions = admin_or_permissions
    commands_mod.Context = Context
    commands_mod.check = lambda f: (lambda func: func)

    # --- redbot.core.config ---
    config_mod = types.ModuleType("redbot.core.config")

    class Config:
        @staticmethod
        def get_conf(cog_instance, *, identifier, force_registration=False):
            return MagicMock()

    config_mod.Config = Config

    # --- redbot.core.bot ---
    bot_mod = types.ModuleType("redbot.core.bot")

    class Red:
        pass

    bot_mod.Red = Red

    # --- redbot.core.data_manager ---
    data_manager_mod = types.ModuleType("redbot.core.data_manager")

    def cog_data_path(cog_instance):
        import tempfile, pathlib
        return pathlib.Path(tempfile.gettempdir()) / "redbot_test_data"

    data_manager_mod.cog_data_path = cog_data_path

    # --- redbot.core (top-level) ---
    core_mod = types.ModuleType("redbot.core")
    core_mod.commands = commands_mod
    core_mod.Config = Config
    core_mod.app_commands = MagicMock()

    # --- redbot (root) ---
    redbot_mod = types.ModuleType("redbot")
    redbot_mod.core = core_mod

    return redbot_mod, core_mod, commands_mod, config_mod, bot_mod, data_manager_mod


(
    redbot_mod,
    core_mod,
    commands_mod,
    config_mod,
    bot_mod,
    data_manager_mod,
) = _build_redbot_stub()

sys.modules.setdefault("redbot", redbot_mod)
sys.modules.setdefault("redbot.core", core_mod)
sys.modules.setdefault("redbot.core.commands", commands_mod)
sys.modules.setdefault("redbot.core.config", config_mod)
sys.modules.setdefault("redbot.core.bot", bot_mod)
sys.modules.setdefault("redbot.core.data_manager", data_manager_mod)
