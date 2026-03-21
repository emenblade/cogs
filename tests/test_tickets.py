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


@pytest.mark.asyncio
async def test_create_ticket_makes_channel_with_sanitized_name():
    """create_ticket must create a channel named {sanitized_username}-{counter:04d}."""
    mock_bot = MagicMock()
    mock_conf = MagicMock()
    guild_conf = MagicMock()
    guild_conf.ticket_category = AsyncMock(return_value=999)
    guild_conf.ticket_counter = AsyncMock(return_value=5)
    guild_conf.ticket_staff_role = AsyncMock(return_value=None)

    async def set_counter(val):
        pass
    guild_conf.ticket_counter.set = AsyncMock(side_effect=set_counter)
    mock_conf.guild = MagicMock(return_value=guild_conf)
    member_conf = MagicMock()
    member_conf.open_tickets = AsyncMock(return_value=[])

    # Make open_tickets work as async context manager
    open_tickets_list = []
    class AsyncListCtx:
        async def __aenter__(self): return open_tickets_list
        async def __aexit__(self, *args): pass
        def __call__(self): return self

    mock_conf.member = MagicMock(return_value=MagicMock(
        open_tickets=AsyncMock(return_value=open_tickets_list)
    ))
    mock_conf.member.return_value.open_tickets = AsyncListCtx()

    mock_interaction = MagicMock()
    mock_interaction.guild = MagicMock()
    mock_interaction.user = MagicMock()
    mock_interaction.user.display_name = "Test User#1234"
    mock_interaction.user.id = 123

    mock_category = MagicMock()
    mock_channel = AsyncMock()
    mock_channel.id = 777
    mock_channel.send = AsyncMock(return_value=MagicMock(id=888))
    mock_category.create_text_channel = AsyncMock(return_value=mock_channel)
    mock_category.overwrites = {}
    mock_interaction.guild.get_channel = MagicMock(return_value=mock_category)
    mock_interaction.guild.me = MagicMock()
    mock_interaction.guild.id = 111

    from forms.tickets import TicketManager
    manager = TicketManager(mock_bot, mock_conf)
    await manager.create_ticket(mock_interaction, "General")

    mock_category.create_text_channel.assert_called_once()
    channel_name = mock_category.create_text_channel.call_args.args[0]
    assert "test" in channel_name  # sanitized
    assert "0006" in channel_name  # counter was 5, incremented to 6
