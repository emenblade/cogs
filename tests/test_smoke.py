"""End-to-end smoke tests: verify all public classes and functions import and instantiate."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
import tempfile


def test_imports_all_public_symbols():
    """All public symbols must be importable without errors."""
    from forms import Forms
    from forms.tickets import TicketManager
    from forms.applications import ApplicationManager
    from forms.views import (
        TicketPanelView, CloseTicketView, ApplyView, ReviewView,
        WizardStep1View, SettingsPanelView,
    )
    from forms.utils import sanitize_channel_name, build_transcript, send_or_attach, check_staff_role


def test_ticket_manager_instantiates():
    from forms.tickets import TicketManager
    manager = TicketManager(MagicMock(), MagicMock())
    assert manager is not None


def test_application_manager_instantiates():
    from forms.applications import ApplicationManager
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ApplicationManager(MagicMock(), MagicMock(), Path(tmpdir))
        manager.initialize()
        assert (Path(tmpdir) / "applications").exists()


@pytest.mark.asyncio
async def test_forms_cog_instantiates_and_initializes():
    from unittest.mock import patch
    with patch("forms.forms.Config") as MockConfig:
        mock_conf = MagicMock()
        mock_conf.register_guild = MagicMock()
        mock_conf.register_member = MagicMock()
        mock_conf.register_user = MagicMock()
        mock_conf.all_guilds = AsyncMock(return_value={})
        mock_conf.all_members = AsyncMock(return_value={})
        MockConfig.get_conf.return_value = mock_conf

        mock_bot = MagicMock()
        mock_bot.add_view = MagicMock()
        mock_bot.get_guild = MagicMock(return_value=None)

        from forms.forms import Forms
        cog = Forms(mock_bot)
        await cog.initialize()
        assert cog.applications is not None
        assert cog.tickets is not None
