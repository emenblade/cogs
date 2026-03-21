# tests/test_utils.py
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from forms.utils import sanitize_channel_name, build_transcript, send_or_attach, check_staff_role


class TestSanitizeChannelName:
    def test_lowercases(self):
        assert sanitize_channel_name("TestUser") == "testuser"

    def test_replaces_spaces_with_hyphens(self):
        assert sanitize_channel_name("test user") == "test-user"

    def test_strips_special_characters(self):
        assert sanitize_channel_name("user#1234!") == "user1234"

    def test_truncates_to_80_chars(self):
        long_name = "a" * 100
        assert len(sanitize_channel_name(long_name)) == 80

    def test_handles_empty_string(self):
        assert sanitize_channel_name("") == "user"

    def test_multiple_hyphens_collapsed(self):
        result = sanitize_channel_name("test  user")
        assert "--" not in result


class TestBuildTranscript:
    def _make_message(self, author_name, content, timestamp_offset=0):
        msg = MagicMock(spec=discord.Message)
        msg.author = MagicMock()
        msg.author.display_name = author_name
        msg.author.bot = False
        msg.content = content
        from datetime import datetime, timezone, timedelta
        msg.created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=timestamp_offset)
        msg.attachments = []
        return msg

    def test_formats_messages_chronologically(self):
        msgs = [
            self._make_message("Alice", "Hello", 0),
            self._make_message("Bob", "Hi there", 1),
        ]
        result = build_transcript(msgs)
        assert "Alice" in result
        assert "Hello" in result
        assert "Bob" in result
        assert result.index("Alice") < result.index("Bob")

    def test_skips_bot_messages(self):
        msg = self._make_message("Bot", "I am a bot")
        msg.author.bot = True
        result = build_transcript([msg])
        assert "I am a bot" not in result

    def test_empty_list_returns_empty_string(self):
        assert build_transcript([]) == ""

    def test_includes_attachment_info(self):
        msg = self._make_message("Alice", "Here is a file")
        att = MagicMock()
        att.filename = "file.png"
        att.url = "https://cdn.example.com/file.png"
        msg.attachments = [att]
        result = build_transcript([msg])
        assert "file.png" in result


@pytest.mark.asyncio
class TestSendOrAttach:
    async def test_sends_inline_when_short(self):
        dest = AsyncMock()
        await send_or_attach(dest, "short content", threshold=1900)
        dest.send.assert_called_once_with("short content")

    async def test_sends_file_when_long(self):
        dest = AsyncMock()
        long_content = "x" * 2000
        await send_or_attach(dest, long_content, filename="t.txt", threshold=1900)
        dest.send.assert_called_once()
        call_kwargs = dest.send.call_args
        assert isinstance(call_kwargs.kwargs.get("file"), discord.File)


class TestCheckStaffRole:
    def test_returns_true_when_member_has_role(self):
        interaction = MagicMock()
        role = MagicMock()
        role.id = 999
        interaction.user = MagicMock()
        interaction.user.roles = [role]
        assert check_staff_role(interaction, 999) is True

    def test_returns_false_when_member_lacks_role(self):
        interaction = MagicMock()
        interaction.user = MagicMock()
        interaction.user.roles = []
        assert check_staff_role(interaction, 999) is False

    def test_returns_false_when_role_id_is_none(self):
        interaction = MagicMock()
        assert check_staff_role(interaction, None) is False

    def test_returns_false_when_user_has_no_roles_attr(self):
        interaction = MagicMock()
        interaction.user = MagicMock(spec=discord.User)  # discord.User has no .roles
        assert check_staff_role(interaction, 999) is False
