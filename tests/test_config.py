# tests/test_config.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_config_registered_with_correct_identifier():
    """Config.get_conf must be called with force_registration=True."""
    from importlib import reload
    import forms.forms
    reload(forms.forms)

    with patch("forms.forms.Config") as mock_config_cls:
        mock_config_cls.get_conf.return_value = MagicMock()
        bot = MagicMock()
        forms.forms.Forms(bot)
        mock_config_cls.get_conf.assert_called_once()
        _, kwargs = mock_config_cls.get_conf.call_args
        assert kwargs.get("force_registration") is True


@pytest.mark.asyncio
async def test_initialize_registers_guild_defaults():
    """initialize() must call config.register_guild with all required keys."""
    from importlib import reload
    import forms.forms
    reload(forms.forms)

    with patch("forms.forms.Config") as mock_config_cls:
        mock_conf = MagicMock()
        mock_conf.register_guild = MagicMock()
        mock_conf.register_member = MagicMock()
        mock_conf.register_user = MagicMock()
        mock_conf.all_guilds = AsyncMock(return_value={})
        mock_conf.all_members = AsyncMock(return_value={})
        mock_config_cls.get_conf.return_value = mock_conf

        bot = MagicMock()
        bot.add_view = MagicMock()
        bot.get_guild = MagicMock(return_value=None)
        cog = forms.forms.Forms(bot)
        await cog.initialize()

        call_kwargs = mock_conf.register_guild.call_args[1]
        required_guild_keys = [
            "ticket_channel", "ticket_category", "ticket_user_role",
            "ticket_staff_role", "ticket_forum", "ticket_categories",
            "ticket_counter", "ticket_panel_message", "ticket_max_open",
            "ticket_tag_id", "application_tag_id", "application_assignments",
        ]
        for key in required_guild_keys:
            assert key in call_kwargs, f"Missing guild config key: {key}"

        member_kwargs = mock_conf.register_member.call_args[1]
        assert "open_tickets" in member_kwargs

        user_kwargs = mock_conf.register_user.call_args[1]
        assert "active_application" in user_kwargs
        assert "application_cooldowns" in user_kwargs

        assert cog.applications is not None
        mock_conf.register_member.assert_called_once()
        mock_conf.register_user.assert_called_once()


@pytest.mark.asyncio
async def test_register_persistent_views_calls_add_view():
    """_register_persistent_views must call bot.add_view for each stored panel message."""
    from importlib import reload
    import forms.forms
    reload(forms.forms)

    with patch("forms.forms.Config") as MockConfig:
        mock_conf = MagicMock()
        mock_conf.register_guild = MagicMock()
        mock_conf.register_member = MagicMock()
        mock_conf.register_user = MagicMock()
        mock_conf.all_guilds = AsyncMock(return_value={
            "111": {
                "ticket_panel_message": 999,
                "ticket_staff_role": None,
                "application_assignments": {},
            }
        })
        mock_conf.all_members = AsyncMock(return_value={})
        MockConfig.get_conf.return_value = mock_conf

        mock_bot = MagicMock()
        mock_bot.add_view = MagicMock()
        mock_bot.get_guild = MagicMock(return_value=None)  # No guild found for CloseTicket iteration

        cog = forms.forms.Forms(mock_bot)
        await cog.initialize()

        mock_bot.add_view.assert_called()
        calls = mock_bot.add_view.call_args_list
        message_ids = [c.kwargs.get("message_id") for c in calls]
        assert 999 in message_ids


@pytest.mark.asyncio
async def test_red_delete_data_for_user_clears_user_config():
    from importlib import reload
    import forms.forms
    reload(forms.forms)

    with patch("forms.forms.Config") as MockConfig:
        mock_conf = MagicMock()
        mock_conf.register_guild = MagicMock()
        mock_conf.register_member = MagicMock()
        mock_conf.register_user = MagicMock()
        mock_conf.all_guilds = AsyncMock(return_value={})
        mock_conf.all_members = AsyncMock(return_value={})

        user_conf = MagicMock()
        user_conf.clear = AsyncMock()
        user_conf.all = AsyncMock(return_value={})
        mock_conf.user = MagicMock(return_value=user_conf)
        MockConfig.get_conf.return_value = mock_conf

        mock_bot = MagicMock()
        mock_bot.add_view = MagicMock()
        mock_bot.get_user = MagicMock(return_value=None)
        mock_bot.guilds = []

        cog = forms.forms.Forms(mock_bot)
        await cog.initialize()
        await cog.red_delete_data_for_user(requester="user", user_id=12345)

        user_conf.clear.assert_called_once()
