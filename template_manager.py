"""Loads document template HTML+JSON pairs from the cog's data directory."""
from __future__ import annotations
import json
from pathlib import Path
from .utils import render_template


class TemplateManager:
    """Reads template pairs dropped into `<cog_data_path>/templates/`.

    Each document type is a `<slug>.json` spec paired with the HTML file it
    names, e.g. `subpoena.json` -> `{"template": "subpoena.html", ...}`. New
    document types are added by dropping in a new pair — no code changes.
    """

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        self.templates_path = data_path / "templates"
        self.documents_path = data_path / "documents"
        self._templates: dict[str, dict] = {}

    def initialize(self) -> None:
        """Create required data directories and do the first template load."""
        self.templates_path.mkdir(parents=True, exist_ok=True)
        self.documents_path.mkdir(parents=True, exist_ok=True)
        self.reload()

    def reload(self) -> dict[str, dict]:
        """Re-scan the templates directory for HTML+JSON pairs. Returns the loaded set."""
        templates: dict[str, dict] = {}
        for spec_path in self.templates_path.glob("*.json"):
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                html_path = self.templates_path / spec["template"]
                if not html_path.exists():
                    continue
                spec["_slug"] = spec_path.stem
                spec["_html_path"] = html_path
                templates[spec_path.stem] = spec
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        self._templates = templates
        return templates

    def all_templates(self) -> dict[str, dict]:
        return self._templates

    def get(self, slug: str) -> dict | None:
        return self._templates.get(slug)

    def render(self, slug: str, answers: dict[str, str]) -> str | None:
        """Render a template's HTML with the given field answers."""
        spec = self.get(slug)
        if spec is None:
            return None
        html = spec["_html_path"].read_text(encoding="utf-8")
        return render_template(html, answers)

    def save_document(self, slug: str, filename: str, rendered_html: str) -> Path:
        """Write a rendered document to `documents/<output_dir>/<filename>`."""
        spec = self.get(slug)
        output_dir = spec.get("output_dir", slug) if spec else slug
        out_dir = self.documents_path / output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / filename
        dest.write_text(rendered_html, encoding="utf-8")
        return dest
