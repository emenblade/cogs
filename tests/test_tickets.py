# tests/test_tickets.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _invoke_button(view, button_name, interaction):
    """Invoke a discord.ui.Button callback correctly for the installed discord.py version.

    In discord.py 2.x the button attribute on a view instance is a Button object whose
    .callback attribute is an _ItemCallback whose .callback attribute is the raw coroutine.
    """
    btn = getattr(view, button_name)
    # btn.callback is _ItemCallback; btn.callback.callback is the raw coroutine function
    raw = btn.callback.callback
    import inspect
    sig = inspect.signature(raw)
    params = list(sig.parameters.keys())
    # raw function has (self, interaction, button) signature
    return raw(view, interaction, MagicMock())


@pytest.mark.asyncio
async def test_open_ticket_blocked_when_no_categories(mock_interaction):
    """Button must send ephemeral error if ticket_categories is empty."""
    mock_conf = MagicMock()
    guild_conf = MagicMock()
    guild_conf.ticket_user_role = AsyncMock(return_value=None)
    guild_conf.ticket_categories = AsyncMock(return_value=[])
    mock_conf.guild = MagicMock(return_value=guild_conf)

    from forms.views import TicketPanelView
    view = TicketPanelView(mock_conf, MagicMock())
    await _invoke_button(view, "open_ticket", mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    args = mock_interaction.response.send_message.call_args
    assert args.kwargs.get("ephemeral") is True
    assert "not fully configured" in args.args[0].lower()


@pytest.mark.asyncio
async def test_open_ticket_blocked_when_max_tickets_reached(mock_interaction):
    """Button must send ephemeral error if user already has max_open tickets."""
    mock_conf = MagicMock()
    guild_conf = MagicMock()
    guild_conf.ticket_user_role = AsyncMock(return_value=None)
    guild_conf.ticket_categories = AsyncMock(return_value=["General"])
    guild_conf.ticket_max_open = AsyncMock(return_value=3)
    mock_conf.guild = MagicMock(return_value=guild_conf)
    member_conf = MagicMock()
    member_conf.open_tickets = AsyncMock(return_value=[1, 2, 3])
    mock_conf.member = MagicMock(return_value=member_conf)

    from forms.views import TicketPanelView
    view = TicketPanelView(mock_conf, MagicMock())
    await _invoke_button(view, "open_ticket", mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    args = mock_interaction.response.send_message.call_args
    assert args.kwargs.get("ephemeral") is True
