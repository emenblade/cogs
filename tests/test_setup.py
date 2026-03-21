# tests/test_setup.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_forms_setup_sends_embed_with_view(mock_bot):
    from forms.forms import Forms
    with patch("forms.forms.Config") as MockConfig:
        mock_conf = MagicMock()
        mock_conf.register_guild = MagicMock()
        mock_conf.register_member = MagicMock()
        mock_conf.register_user = MagicMock()
        MockConfig.get_conf.return_value = mock_conf

        cog = Forms(mock_bot)
        await cog.initialize()

        ctx = AsyncMock()
        ctx.guild = MagicMock()
        ctx.guild.id = 111111111111111111
        ctx.send = AsyncMock()

        await cog.forms_setup(ctx)
        ctx.send.assert_called_once()
        call_kwargs = ctx.send.call_args.kwargs
        assert "embed" in call_kwargs
        assert "view" in call_kwargs
