"""Thin GitHub REST API client used to fetch templates and publish filings.

Uses aiohttp (already a Red dependency) rather than a dedicated GitHub SDK,
to keep the bot's runtime footprint light. Reads work unauthenticated for
public repos (at a lower rate limit); writes always require a token.
"""
from __future__ import annotations
import base64
import aiohttp
from redbot.core.bot import Red

API_BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def get_token(self) -> str | None:
        tokens = await self.bot.get_shared_api_tokens("github")
        return tokens.get("token")

    async def _headers(self, *, need_token: bool = False, raw: bool = False) -> dict[str, str] | None:
        headers = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json"}
        token = await self.get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif need_token:
            return None
        return headers

    async def list_directory(self, owner: str, repo: str, path: str, branch: str) -> list[dict]:
        """List files in a repo directory. Returns [] if the path doesn't exist."""
        session = await self._get_session()
        headers = await self._headers()
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
        async with session.get(url, headers=headers, params={"ref": branch}) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data if isinstance(data, list) else []

    async def get_file_text(self, owner: str, repo: str, path: str, branch: str) -> str | None:
        """Fetch a single file's raw text content, or None if it doesn't exist."""
        session = await self._get_session()
        headers = await self._headers(raw=True)
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
        async with session.get(url, headers=headers, params={"ref": branch}) as resp:
            if resp.status != 200:
                return None
            return await resp.text()

    async def _get_sha(self, owner: str, repo: str, path: str, branch: str) -> str | None:
        session = await self._get_session()
        headers = await self._headers()
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
        async with session.get(url, headers=headers, params={"ref": branch}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data.get("sha") if isinstance(data, dict) else None

    async def put_file(
        self, owner: str, repo: str, path: str, content: str, message: str, branch: str
    ) -> bool:
        """Create or update a file. Returns False if no token is configured or the push fails."""
        headers = await self._headers(need_token=True)
        if headers is None:
            return False
        session = await self._get_session()
        sha = await self._get_sha(owner, repo, path, branch)
        body = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
        async with session.put(url, headers=headers, json=body) as resp:
            return resp.status in (200, 201)

    async def delete_file(self, owner: str, repo: str, path: str, message: str, branch: str) -> bool:
        """Delete a file. Returns False if no token is configured, the file doesn't exist, or it fails."""
        headers = await self._headers(need_token=True)
        if headers is None:
            return False
        sha = await self._get_sha(owner, repo, path, branch)
        if not sha:
            return False
        session = await self._get_session()
        body = {"message": message, "sha": sha, "branch": branch}
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
        async with session.delete(url, headers=headers, json=body) as resp:
            return resp.status == 200
