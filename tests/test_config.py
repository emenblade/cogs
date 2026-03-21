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
        mock_config_cls.get_conf.return_value = mock_conf

        bot = MagicMock()
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
