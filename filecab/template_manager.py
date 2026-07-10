"""Loads document template HTML+JSON pairs and classifies their fields."""
from __future__ import annotations
import json
from pathlib import Path
from .utils import render_template


class TemplateManager:
    """Reads template pairs from `<cog_data_path>/templates/`.

    Each document type is a `<template_id>.json` manifest paired with the
    HTML file it names in `"html_file"`. Templates are populated by fetching
    them from the configured site repo (see `refresh_from_repo` and
    `filecab refresh`) — the repo is the source of truth, not anything
    bundled with the cog. See docs/SITE_REPO_CONTRACT.md for the schema a
    site repo's `templates/` directory must follow.
    """

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        self.templates_path = data_path / "templates"
        self.documents_path = data_path / "documents"
        self._templates: dict[str, dict] = {}

    def initialize(self) -> None:
        """Create required data directories and load whatever's already on disk."""
        self.templates_path.mkdir(parents=True, exist_ok=True)
        self.documents_path.mkdir(parents=True, exist_ok=True)
        self.reload()

    async def refresh_from_repo(self, github, owner: str, repo: str, branch: str) -> int:
        """Fetch every template pair from `<repo>/templates/` and reload. Returns the count fetched.

        Also opportunistically fetches `templates/<template_id>.png` as an optional preview
        image — purely cosmetic, so a missing one is silently skipped rather than treated
        as a fetch failure.
        """
        entries = await github.list_directory(owner, repo, "templates", branch)
        json_entries = [
            e for e in entries
            if e.get("name", "").endswith(".json") and e.get("type") == "file" and e.get("name") != "index.json"
        ]

        fetched = 0
        for entry in json_entries:
            text = await github.get_file_text(owner, repo, entry["path"], branch)
            if text is None:
                continue
            try:
                spec = json.loads(text)
                template_id = spec["template_id"]
                html_file = spec["html_file"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            html_text = await github.get_file_text(owner, repo, f"templates/{html_file}", branch)
            if html_text is None:
                continue

            (self.templates_path / entry["name"]).write_text(text, encoding="utf-8")
            (self.templates_path / html_file).write_text(html_text, encoding="utf-8")

            image_bytes = await github.get_file_bytes(owner, repo, f"templates/{template_id}.png", branch)
            if image_bytes is not None:
                (self.templates_path / f"{template_id}.png").write_bytes(image_bytes)

            fetched += 1

        self.reload()
        return fetched

    def preview_image_path(self, template_id: str) -> Path | None:
        """Return a template's optional preview image path, or None if it doesn't have one."""
        path = self.templates_path / f"{template_id}.png"
        return path if path.exists() else None

    def reload(self) -> dict[str, dict]:
        """Re-scan the templates directory for HTML+JSON pairs. Returns the loaded set."""
        templates: dict[str, dict] = {}
        for spec_path in self.templates_path.glob("*.json"):
            try:
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                template_id = spec["template_id"]
                html_path = self.templates_path / spec["html_file"]
                if not html_path.exists():
                    continue
                spec["_html_path"] = html_path
                self._infer_missing_fill_at(spec)
                templates[template_id] = spec
            except (json.JSONDecodeError, KeyError, TypeError, OSError):
                continue
        self._templates = templates
        return templates

    @staticmethod
    def _infer_missing_fill_at(spec: dict) -> None:
        """Fill in "fill_at" on any "auto" field that doesn't already have one.

        Templates aren't required to set this explicitly. When it's missing,
        infer it from position relative to the first approval-time judge
        field (the one real signal available): auto fields before that point
        are due at submission, ones at/after it are due at approval. Mutates
        the field dicts in place.
        """
        fields = spec.get("fields", [])
        first_approval_judge_idx = next(
            (i for i, f in enumerate(fields) if f.get("filled_by") == "judge" and f.get("prompt") is None),
            None,
        )
        for i, field in enumerate(fields):
            if field.get("filled_by") == "auto" and not field.get("fill_at"):
                if first_approval_judge_idx is not None and i > first_approval_judge_idx:
                    field["fill_at"] = "approval"
                else:
                    field["fill_at"] = "submission"

    def all_templates(self) -> dict[str, dict]:
        return self._templates

    def get(self, template_id: str) -> dict | None:
        return self._templates.get(template_id)

    @staticmethod
    def is_staff_authored(spec: dict) -> bool:
        """True if no field is filled by a citizen applicant (judge-authored doc)."""
        return not any(f["filled_by"] == "applicant" for f in spec["fields"])

    @staticmethod
    def prompted_fields(spec: dict) -> list[dict]:
        """Fields asked over DM, in order — anything with a non-null prompt."""
        return [f for f in spec["fields"] if f.get("prompt") is not None]

    @staticmethod
    def field_applies(field: dict, answers: dict[str, str]) -> bool:
        """True if a field's `depends_on` condition (if any) is met by the answers so far.

        `depends_on` is `{"field": key, "equals": value}`, always referencing an
        earlier field in the same template — by the time a later field is being
        considered, whatever it depends on has already been asked (or skipped and
        auto-filled). A field with no `depends_on` always applies.
        """
        depends_on = field.get("depends_on")
        if not depends_on:
            return True
        return answers.get(depends_on["field"]) == depends_on["equals"]

    def advance_past_skipped(
        self, spec: dict, answers: dict[str, str], index: int
    ) -> tuple[int, dict[str, str]]:
        """From `index` into `prompted_fields(spec)`, auto-fill and skip past every field
        whose `depends_on` condition isn't met, given `answers` so far.

        Returns the index of the next field that should actually be asked — equal to
        `len(prompted_fields(spec))` once nothing's left — plus an updated copy of
        `answers` with each skipped field's `skip_value` filled in (empty string if a
        conditional field omits `skip_value`).
        """
        prompted = self.prompted_fields(spec)
        answers = dict(answers)
        while index < len(prompted) and not self.field_applies(prompted[index], answers):
            field = prompted[index]
            answers[field["key"]] = field.get("skip_value", "")
            index += 1
        return index, answers

    @staticmethod
    def approval_judge_fields(spec: dict) -> list[dict]:
        """Fields collected from the approving staff member, not the filer."""
        return [f for f in spec["fields"] if f["filled_by"] == "judge" and f.get("prompt") is None]

    @staticmethod
    def auto_fields(spec: dict, fill_at: str) -> list[dict]:
        """Auto-computed fields due at a given point ("submission" or "approval")."""
        return [
            f for f in spec["fields"]
            if f["filled_by"] == "auto" and f.get("fill_at") == fill_at
        ]

    @staticmethod
    def handoff_signers(spec: dict) -> list[dict]:
        """Signer roster entries that need a real Discord member assigned to sign."""
        return [s for s in spec.get("signers", []) if s.get("requires_handoff")]

    @staticmethod
    def signer_fields(spec: dict, role: str) -> list[dict]:
        """Fields collected from the person assigned to the given signer role."""
        return [f for f in spec["fields"] if f["filled_by"] == role]

    def render(self, template_id: str, answers: dict[str, str]) -> str | None:
        """Render a template's HTML with the given field answers."""
        spec = self.get(template_id)
        if spec is None:
            return None
        html = spec["_html_path"].read_text(encoding="utf-8")
        return render_template(html, answers)

    def save_document(self, template_id: str, filing_id: str, rendered_html: str) -> Path:
        """Write a rendered document to `documents/<template_id>/<filing_id>.html`."""
        out_dir = self.documents_path / template_id
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{filing_id}.html"
        dest.write_text(rendered_html, encoding="utf-8")
        return dest

    def save_sidecar(self, template_id: str, filing_id: str, sidecar: dict) -> Path:
        """Write the filing's metadata sidecar next to its rendered HTML."""
        out_dir = self.documents_path / template_id
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{filing_id}.json"
        dest.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return dest
