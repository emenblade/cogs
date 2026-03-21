import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
from pathlib import Path
import tempfile


@pytest.mark.asyncio
async def test_save_application_writes_json_file():
    """ApplicationManager must save a JSON file named {slug}.json."""
    mock_bot = MagicMock()
    mock_conf = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        from forms.applications import ApplicationManager
        manager = ApplicationManager(mock_bot, mock_conf, Path(tmpdir))
        manager.initialize()

        await manager._save_application({
            "name": "Mod Application",
            "slug": "mod-application",
            "description": "Test desc",
            "questions": ["Q1", "Q2"],
        })

        app_file = Path(tmpdir) / "applications" / "mod-application.json"
        assert app_file.exists()
        data = json.loads(app_file.read_text())
        assert data["name"] == "Mod Application"
        assert data["questions"] == ["Q1", "Q2"]


@pytest.mark.asyncio
async def test_load_applications_returns_all_json_files():
    """load_applications must return a dict of all saved application templates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_dir = Path(tmpdir) / "applications"
        app_dir.mkdir()
        (app_dir / "mod-application.json").write_text(json.dumps({
            "name": "Mod Application", "slug": "mod-application",
            "description": "desc", "questions": ["Q1"]
        }))
        (app_dir / "builder.json").write_text(json.dumps({
            "name": "Builder", "slug": "builder",
            "description": "desc2", "questions": ["Q2"]
        }))

        from forms.applications import ApplicationManager
        manager = ApplicationManager(MagicMock(), MagicMock(), Path(tmpdir))
        apps = await manager.load_applications()
        assert "mod-application" in apps
        assert "builder" in apps
        assert apps["mod-application"]["name"] == "Mod Application"


@pytest.mark.asyncio
async def test_assign_application_saves_to_config():
    """assign_application must save channel_id, approval_role_id, and cooldown_days to config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_conf = MagicMock()
        guild_conf = MagicMock()
        existing_assignments = {}
        guild_conf.application_assignments = AsyncMock(return_value=existing_assignments)
        guild_conf.application_assignments.set = AsyncMock()
        mock_conf.guild = MagicMock(return_value=guild_conf)

        from forms.applications import ApplicationManager
        manager = ApplicationManager(MagicMock(), mock_conf, Path(tmpdir))

        mock_channel = MagicMock()
        mock_channel.id = 123
        mock_channel.send = AsyncMock(return_value=MagicMock(id=456))
        mock_guild = MagicMock()
        mock_guild.id = 111

        await manager.assign_application(
            guild=mock_guild,
            slug="mod-application",
            name="Mod Application",
            description="Join the mod team",
            channel=mock_channel,
            approval_role_id=789,
            cooldown_days=7,
        )

        guild_conf.application_assignments.set.assert_called_once()
        saved = guild_conf.application_assignments.set.call_args.args[0]
        assert "mod-application" in saved
        assert saved["mod-application"]["channel_id"] == 123
        assert saved["mod-application"]["approval_role_id"] == 789
        assert saved["mod-application"]["cooldown_days"] == 7
