import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.guild = MagicMock(return_value=MagicMock())
    config.member = MagicMock(return_value=MagicMock())
    config.user = MagicMock(return_value=MagicMock())
    return config


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.get_guild = MagicMock(return_value=None)
    return bot


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 111111111111111111
    guild.name = "Test Server"
    return guild


@pytest.fixture
def mock_member(mock_guild):
    member = MagicMock(spec=discord.Member)
    member.id = 222222222222222222
    member.name = "testuser"
    member.display_name = "Test User"
    member.guild = mock_guild
    member.roles = []
    return member


@pytest.fixture
def mock_interaction(mock_member, mock_guild):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = mock_member
    interaction.guild = mock_guild
    interaction.guild_id = mock_guild.id
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    return interaction
