"""Publishing finished documents to the configured site repo (e.g. emenblade/lcrpfilecab).

Pushes `filings/<template_id>/<filing_id>.html` and its sidecar `.json` (see
TemplateManager.save_document/save_sidecar for the exact shape) via the
GitHub Contents API. The site's own GitHub Action rebuilds
`filings-index.json`/`index.html` automatically on that push — nothing else
is needed from the bot. See docs/SITE_REPO_CONTRACT.md for the full contract.
"""
from __future__ import annotations
from pathlib import Path
from redbot.core import Config
from .github_client import GitHubClient
from .utils import normalize_base_url


class DocumentPublisher:
    def __init__(self, config: Config, github: GitHubClient) -> None:
        self.config = config
        self.github = github

    async def _site_coords(self) -> tuple[str, str, str] | None:
        """Return (owner, repo, branch), or None if no site repo is configured."""
        site_repo = await self.config.site_repo()
        if not site_repo or "/" not in site_repo:
            return None
        owner, repo = site_repo.split("/", 1)
        branch = await self.config.site_branch()
        return owner, repo, branch

    async def _base_url(self, owner: str, repo: str) -> str:
        base_url = await self.config.site_base_url()
        return normalize_base_url(base_url) if base_url else f"https://{owner}.github.io/{repo}"

    async def publish(self, html_path: Path, json_path: Path, template_id: str, filing_id: str) -> str | None:
        """Push a filing's rendered HTML + sidecar JSON to the documents site.

        Returns the document's live URL, or None if publishing isn't possible
        right now (no site repo configured, no GitHub token, or the push
        failed) — callers must handle the None case.
        """
        coords = await self._site_coords()
        if coords is None:
            return None
        owner, repo, branch = coords

        html_ok = await self.github.put_file(
            owner, repo, f"filings/{template_id}/{filing_id}.html",
            html_path.read_text(encoding="utf-8"),
            f"file {filing_id}", branch,
        )
        if not html_ok:
            return None
        json_ok = await self.github.put_file(
            owner, repo, f"filings/{template_id}/{filing_id}.json",
            json_path.read_text(encoding="utf-8"),
            f"file {filing_id} (metadata)", branch,
        )
        if not json_ok:
            return None

        base_url = await self._base_url(owner, repo)
        return f"{base_url}/filings/{template_id}/{filing_id}.html"

    async def unpublish(self, template_id: str, filing_id: str) -> bool:
        """Remove a previously published document from the documents site."""
        coords = await self._site_coords()
        if coords is None:
            return False
        owner, repo, branch = coords

        html_ok = await self.github.delete_file(
            owner, repo, f"filings/{template_id}/{filing_id}.html", f"remove {filing_id}", branch
        )
        json_ok = await self.github.delete_file(
            owner, repo, f"filings/{template_id}/{filing_id}.json", f"remove {filing_id} (metadata)", branch
        )
        return html_ok or json_ok
