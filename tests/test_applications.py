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
