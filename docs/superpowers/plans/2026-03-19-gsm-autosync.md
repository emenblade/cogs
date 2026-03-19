# gsm-autosync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Red-DiscordBot cog that watches Docker events and auto-adds/removes game server entries from DiscordGSM's SQLite database.

**Architecture:** A background thread streams Docker events via the Docker Python SDK. On container start/stop, the main async loop writes to DiscordGSM's `servers.db`. All guild config (channel, DB path, monitored containers, tracked row IDs, saved style_data) lives in Red's per-guild Config system. The cog only ever touches rows it created.

**Tech Stack:** Python 3.10+, Red-DiscordBot 3.5, discord.py 2.x, Docker Python SDK (`docker`), sqlite3 (stdlib), pytest + unittest.mock for tests.

---

## File Map

| Path | Role |
|---|---|
| `gsm-autosync/__init__.py` | Red async setup entrypoint |
| `gsm-autosync/gsm_autosync.py` | Main cog class: commands, lifecycle, event dispatch |
| `gsm-autosync/game_map.py` | Pure data: container name → game_id, port, display name, query_extra |
| `gsm-autosync/db.py` | SQLite helpers: insert, delete, position query |
| `gsm-autosync/docker_listener.py` | Background thread: Docker event stream + callback |
| `gsm-autosync/info.json` | Red cog metadata + pip requirements |
| `gsm-autosync/requirements.txt` | `docker` |
| `tests/test_game_map.py` | Unit tests for game_map lookups |
| `tests/test_db.py` | Unit tests for DB helpers (using temp SQLite file) |
| `README.md` | Install instructions for the repo |

---

## Task 1: Initialize Git and Scaffold Package

**Files:**
- Create: `gsm-autosync/__init__.py`
- Create: `gsm-autosync/info.json`
- Create: `gsm-autosync/requirements.txt`
- Create: `README.md`

- [ ] **Step 1: Initialize git and connect to remote**

```bash
cd "C:\Users\emenb\Documents\repos\Red cogs\Server monitor"
git init
git remote add origin https://github.com/emenblade/cogs.git
git branch -M main
```

- [ ] **Step 2: Create `gsm-autosync/__init__.py`**

```python
from .gsm_autosync import GsmAutoSync

async def setup(bot):
    await bot.add_cog(GsmAutoSync(bot))
```

- [ ] **Step 3: Create `gsm-autosync/info.json`**

```json
{
    "author": ["emenblade"],
    "description": "Watches Docker for game server containers and automatically adds/removes them from DiscordGSM's database. Requires /var/run/docker.sock mounted in the Red bot container.",
    "short": "Auto-sync game servers to DiscordGSM",
    "install_msg": "Before loading: ensure /var/run/docker.sock is mounted in your Red bot container, and your DiscordGSM appdata is mounted at /discordgsm. Then run `[p]gsmsetup channel #your-channel` followed by `[p]gsmsetup scan`.",
    "end_user_data_statement": "This cog stores per-guild configuration including channel IDs, database paths, container mappings, and style preferences. No user personal data is stored.",
    "min_bot_version": "3.5.0",
    "min_python_version": [3, 10, 0],
    "requirements": ["docker"],
    "tags": ["docker", "gameserver", "discordgsm", "unraid"],
    "type": "COG"
}
```

- [ ] **Step 4: Create `gsm-autosync/requirements.txt`**

```
docker
```

- [ ] **Step 5: Create `README.md`**

```markdown
# cogs — emenblade's Red-DiscordBot Cogs

## gsm-autosync

Watches Docker for game server containers starting/stopping and automatically syncs them to DiscordGSM's database. Status cards appear in Discord without manual setup.

### Prerequisites

1. Mount Docker socket in your Red bot container (add to Extra Parameters in Unraid):
   `-v /var/run/docker.sock:/var/run/docker.sock`
2. Mount DiscordGSM appdata into the Red bot container:
   `/mnt/user/appdata/discordgsm` → `/discordgsm` (mode: rw)

### Install

```
[p]repo add cogs https://github.com/emenblade/cogs
[p]cog install cogs gsm-autosync
[p]load gsm-autosync
```

### Setup

```
[p]gsmsetup channel #your-channel
[p]gsmsetup scan
[p]gsmsetup status
```

### Commands

| Command | Description |
|---|---|
| `[p]gsmsetup channel #channel` | Set the Discord channel for GSM cards |
| `[p]gsmsetup dbpath /path/to/db` | Override default DB path (/discordgsm/servers.db) |
| `[p]gsmsetup addgame <name> <game_id> <port>` | Manually map a container |
| `[p]gsmsetup removegame <name>` | Remove a custom mapping |
| `[p]gsmsetup scan` | Interactive container selection |
| `[p]gsmsetup list` | Show current config |
| `[p]gsmsetup status` | Health check |
```

- [ ] **Step 6: Create `tests/` directory placeholder**

Create an empty `tests/__init__.py`:
```python
```

- [ ] **Step 7: Initial commit**

```bash
git add gsm-autosync/ tests/ README.md .gitignore docs/ my-red-discordbotGSM.xml PROJECT_CONTEXT.md
git commit -m "chore: scaffold gsm-autosync cog package"
```

---

## Task 2: game_map.py

**Files:**
- Create: `gsm-autosync/game_map.py`
- Create: `tests/test_game_map.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_game_map.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gsm-autosync'))

from game_map import get_game_info, GAME_MAP

def test_exact_match():
    info = get_game_info("Valheim")
    assert info is not None
    assert info["game_id"] == "valheim"
    assert info["query_port"] == 2457

def test_case_insensitive_match():
    assert get_game_info("valheim") is not None
    assert get_game_info("VALHEIM") is not None

def test_unknown_container_returns_none():
    assert get_game_info("nginx") is None
    assert get_game_info("plex") is None
    assert get_game_info("") is None

def test_minecraft_variants():
    assert get_game_info("MinecraftBasicServer")["game_id"] == "minecraft"
    assert get_game_info("binhex-minecraftserver")["game_id"] == "minecraft"
    assert get_game_info("Minecraft-forge")["game_id"] == "minecraft"

def test_dst_game_id():
    info = get_game_info("DontStarveTogether")
    assert info["game_id"] == "dst"

def test_all_entries_have_required_fields():
    required = {"game_id", "query_port", "query_extra", "display_name"}
    for name, info in GAME_MAP.items():
        assert required.issubset(info.keys()), f"{name} missing fields"

def test_query_extra_is_dict():
    for name, info in GAME_MAP.items():
        assert isinstance(info["query_extra"], dict), f"{name} query_extra must be dict"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "C:\Users\emenb\Documents\repos\Red cogs\Server monitor"
python -m pytest tests/test_game_map.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — `game_map` doesn't exist yet.

- [ ] **Step 3: Create `gsm-autosync/game_map.py`**

```python
"""
Container name → DiscordGSM game info lookup table.

game_id strings verified against DiscordGSM's supported games list.
query_port is the UDP query port (not the game port).
query_extra is passed directly to DiscordGSM — {} is correct for all listed games.
"""

GAME_MAP = {
    "satisfactory": {
        "game_id": "satisfactory",
        "query_port": 15777,
        "query_extra": {},
        "display_name": "Satisfactory",
    },
    "v-rising": {
        "game_id": "vrising",
        "query_port": 9877,
        "query_extra": {},
        "display_name": "V Rising",
    },
    "corekeeper": {
        "game_id": "corekeeper",
        "query_port": 27016,
        "query_extra": {},
        "display_name": "Core Keeper",
    },
    "dontstarvetogether": {
        "game_id": "dst",
        "query_port": 27016,
        "query_extra": {},
        "display_name": "Don't Starve Together",
    },
    "valheim": {
        "game_id": "valheim",
        "query_port": 2457,
        "query_extra": {},
        "display_name": "Valheim",
    },
    "minecraftbasicserver": {
        "game_id": "minecraft",
        "query_port": 25565,
        "query_extra": {},
        "display_name": "Minecraft",
    },
    "binhex-minecraftserver": {
        "game_id": "minecraft",
        "query_port": 25565,
        "query_extra": {},
        "display_name": "Minecraft",
    },
    "minecraft-forge": {
        "game_id": "minecraft",
        "query_port": 25565,
        "query_extra": {},
        "display_name": "Minecraft (Forge)",
    },
}


def get_game_info(container_name: str) -> dict | None:
    """Return game info for a container name, or None if not recognized.

    Matching is case-insensitive.
    """
    if not container_name:
        return None
    return GAME_MAP.get(container_name.lower())
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_game_map.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add gsm-autosync/game_map.py tests/test_game_map.py
git commit -m "feat: add game_map with verified DiscordGSM game IDs"
```

---

## Task 3: DB Helpers

**Files:**
- Create: `gsm-autosync/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_db.py`:

```python
import sys, os, sqlite3, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gsm-autosync'))

import pytest
from db import (
    create_schema_if_missing,
    insert_server,
    delete_server_by_id,
    get_server_by_id,
    is_db_writable,
)

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "servers.db")
    create_schema_if_missing(db_path)
    return db_path

def test_insert_returns_row_id(tmp_db):
    row_id = insert_server(tmp_db, {
        "guild_id": 111,
        "channel_id": 222,
        "game_id": "valheim",
        "address": "172.17.0.5",
        "query_port": 2457,
        "query_extra": "{}",
        "style_data": json.dumps({"fullname": "Valheim", "country": "CA"}),
    })
    assert isinstance(row_id, int)
    assert row_id > 0

def test_position_increments(tmp_db):
    id1 = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "valheim",
        "address": "172.17.0.5", "query_port": 2457,
        "query_extra": "{}", "style_data": "{}",
    })
    id2 = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "minecraft",
        "address": "172.17.0.6", "query_port": 25565,
        "query_extra": "{}", "style_data": "{}",
    })
    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT position FROM servers ORDER BY id").fetchall()
    conn.close()
    assert rows[1][0] > rows[0][0]

def test_delete_by_id(tmp_db):
    row_id = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "valheim",
        "address": "172.17.0.5", "query_port": 2457,
        "query_extra": "{}", "style_data": "{}",
    })
    delete_server_by_id(tmp_db, row_id)
    assert get_server_by_id(tmp_db, row_id) is None

def test_delete_nonexistent_is_safe(tmp_db):
    # Should not raise
    delete_server_by_id(tmp_db, 99999)

def test_get_style_data_preserved(tmp_db):
    style = json.dumps({"fullname": "Valheim", "country": "CA", "description": "my server"})
    row_id = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "valheim",
        "address": "172.17.0.5", "query_port": 2457,
        "query_extra": "{}", "style_data": style,
    })
    row = get_server_by_id(tmp_db, row_id)
    assert row["style_data"] == style

def test_is_db_writable_true(tmp_db):
    assert is_db_writable(tmp_db) is True

def test_is_db_writable_false_missing_path():
    assert is_db_writable("/nonexistent/path/servers.db") is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_db.py -v
```
Expected: `ImportError` — `db` module doesn't exist yet.

- [ ] **Step 3: Create `gsm-autosync/db.py`**

```python
"""SQLite helpers for interacting with DiscordGSM's servers.db.

All functions open and close their own connection to stay safe under
concurrent access with DiscordGSM. timeout=10 handles SQLITE_BUSY.
"""

import sqlite3
import json
import os
import logging

log = logging.getLogger("red.gsm-autosync.db")

_TIMEOUT = 10  # seconds to wait on SQLITE_BUSY


def create_schema_if_missing(db_path: str) -> None:
    """Create the servers table if it doesn't exist.

    Safe to call on an existing DiscordGSM database — uses IF NOT EXISTS.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position INT NOT NULL DEFAULT 0,
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                message_id BIGINT,
                game_id TEXT NOT NULL,
                address TEXT NOT NULL,
                query_port INT NOT NULL,
                query_extra TEXT NOT NULL DEFAULT '{}',
                status INT NOT NULL DEFAULT 1,
                result TEXT NOT NULL DEFAULT '{}',
                style_id TEXT NOT NULL DEFAULT 'Large',
                style_data TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        log.error("Failed to create schema: %s", e)


def insert_server(db_path: str, data: dict) -> int | None:
    """Insert a server row and return the new row id.

    data keys: guild_id, channel_id, game_id, address, query_port,
               query_extra (str), style_data (str JSON)
    Returns the new row id, or None on failure.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.execute("SELECT MAX(position) FROM servers")
            max_pos = cur.fetchone()[0]
            position = (max_pos + 1) if max_pos is not None else 0

            cur = conn.execute("""
                INSERT INTO servers
                    (position, guild_id, channel_id, message_id, game_id,
                     address, query_port, query_extra, status, result,
                     style_id, style_data)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 1, '{}', 'Large', ?)
            """, (
                position,
                data["guild_id"],
                data["channel_id"],
                data["game_id"],
                data["address"],
                data["query_port"],
                data["query_extra"],
                data["style_data"],
            ))
            return cur.lastrowid
    except sqlite3.OperationalError as e:
        log.error("Failed to insert server row: %s", e)
        return None
    finally:
        conn.close()


def delete_server_by_id(db_path: str, row_id: int) -> None:
    """Delete a server row by its primary key id."""
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        with conn:
            conn.execute("DELETE FROM servers WHERE id = ?", (row_id,))
    except sqlite3.OperationalError as e:
        log.error("Failed to delete server row id=%s: %s", row_id, e)
    finally:
        conn.close()


def get_server_by_id(db_path: str, row_id: int) -> dict | None:
    """Return a server row as a dict, or None if not found."""
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM servers WHERE id = ?", (row_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.OperationalError as e:
        log.error("Failed to get server row id=%s: %s", row_id, e)
        return None


def is_db_writable(db_path: str) -> bool:
    """Return True if the DB file exists and is writable."""
    try:
        if not os.path.exists(db_path):
            # Try creating it (new setup)
            conn = sqlite3.connect(db_path, timeout=2)
            conn.close()
            return True
        return os.access(db_path, os.W_OK)
    except Exception:
        return False
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_db.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add gsm-autosync/db.py tests/test_db.py
git commit -m "feat: add SQLite DB helpers with insert, delete, and writability check"
```

---

## Task 4: Docker Listener

**Files:**
- Create: `gsm-autosync/docker_listener.py`

No unit tests for this module — it wraps a live socket. Manual verification via `[p]gsmsetup status`.

- [ ] **Step 1: Create `gsm-autosync/docker_listener.py`**

```python
"""Background thread that streams Docker events and fires callbacks.

Usage:
    listener = DockerListener(on_start=my_async_fn, on_stop=my_async_fn, loop=asyncio_loop)
    listener.start()
    # ... later ...
    listener.stop()  # blocks up to 5s for clean exit
"""

import threading
import logging
from typing import Callable, Awaitable
import asyncio

log = logging.getLogger("red.gsm-autosync.docker_listener")

try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False


class DockerListener(threading.Thread):
    """Streams Docker container events in a background thread.

    Calls on_start(container_name, container_id) or
          on_stop(container_name, container_id)
    as asyncio coroutines scheduled on the provided event loop.
    """

    def __init__(
        self,
        on_start: Callable[[str, str], Awaitable[None]],
        on_stop: Callable[[str, str], Awaitable[None]],
        loop: asyncio.AbstractEventLoop,
    ):
        super().__init__(daemon=True, name="gsm-autosync-docker-listener")
        self._on_start = on_start
        self._on_stop = on_stop
        self._loop = loop
        self._client = None
        self._running = False

    def run(self):
        if not DOCKER_AVAILABLE:
            log.error("docker package not installed")
            return

        try:
            self._client = docker.from_env()
        except Exception as e:
            log.error("Failed to connect to Docker socket: %s", e)
            return

        self._running = True
        log.info("Docker event listener started")

        try:
            for event in self._client.events(decode=True, filters={"type": "container"}):
                if not self._running:
                    break
                action = event.get("Action", "")
                attrs = event.get("Actor", {}).get("Attributes", {})
                name = attrs.get("name", "")
                cid = event.get("Actor", {}).get("ID", "")[:12]

                if action == "start":
                    asyncio.run_coroutine_threadsafe(
                        self._on_start(name, cid), self._loop
                    )
                elif action in ("die", "stop"):
                    asyncio.run_coroutine_threadsafe(
                        self._on_stop(name, cid), self._loop
                    )
        except Exception as e:
            if self._running:
                log.error("Docker event stream error: %s", e)
        finally:
            log.info("Docker event listener stopped")

    def stop(self):
        """Signal the thread to stop and close the Docker client."""
        self._running = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self.join(timeout=5)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._running

    @staticmethod
    def docker_available() -> bool:
        if not DOCKER_AVAILABLE:
            return False
        try:
            client = docker.from_env()
            client.ping()
            client.close()
            return True
        except Exception:
            return False

    @staticmethod
    def get_container_ip(container_name: str) -> str | None:
        """Return the bridge network IP for a container, or None."""
        if not DOCKER_AVAILABLE:
            return None
        try:
            client = docker.from_env()
            container = client.containers.get(container_name)
            networks = container.attrs["NetworkSettings"]["Networks"]
            client.close()
            # Prefer bridge network; fall back to first available
            if "bridge" in networks:
                return networks["bridge"]["IPAddress"] or None
            for net in networks.values():
                ip = net.get("IPAddress")
                if ip:
                    return ip
            return None
        except Exception as e:
            log.error("Failed to get IP for container %s: %s", container_name, e)
            return None

    @staticmethod
    def list_running_containers() -> list[str]:
        """Return names of all currently running containers."""
        if not DOCKER_AVAILABLE:
            return []
        try:
            client = docker.from_env()
            containers = client.containers.list()
            names = [c.name for c in containers]
            client.close()
            return names
        except Exception as e:
            log.error("Failed to list containers: %s", e)
            return []
```

- [ ] **Step 2: Commit**

```bash
git add gsm-autosync/docker_listener.py
git commit -m "feat: add Docker event listener background thread"
```

---

## Task 5: Main Cog — Skeleton + Config Registration

**Files:**
- Create: `gsm-autosync/gsm_autosync.py`

- [ ] **Step 1: Create `gsm-autosync/gsm_autosync.py` with Config schema and lifecycle hooks**

```python
"""gsm-autosync — Main cog.

Watches Docker events and syncs game server containers into DiscordGSM's
servers.db automatically.
"""

import asyncio
import json
import logging
import os

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .db import insert_server, delete_server_by_id, get_server_by_id, is_db_writable, create_schema_if_missing
from .docker_listener import DockerListener
from .game_map import get_game_info, GAME_MAP

log = logging.getLogger("red.gsm-autosync")

_DEFAULT_DB_PATH = os.environ.get("GSM_DB_PATH", "/discordgsm/servers.db")

DEFAULT_STYLE_DATA = {
    "fullname": "",
    "locale": "en-US",
    "description": "",
    "image_url": "",
    "thumbnail_url": "",
    "country": "CA",
}


class GsmAutoSync(commands.Cog):
    """Auto-sync game server containers to DiscordGSM."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8675309420, force_registration=True)

        self.config.register_guild(
            channel_id=None,          # Discord channel for GSM cards
            db_path=_DEFAULT_DB_PATH, # Path to servers.db inside container
            custom_games={},          # {container_name: {game_id, query_port, display_name}}
            monitored=None,           # Set of container names to monitor (None = use game_map defaults)
            tracked_rows={},          # {container_name: db_row_id}
            saved_style_data={},      # {container_name: style_data dict}
        )

        self._listener: DockerListener | None = None

    async def cog_load(self):
        """Start Docker event listener and sync running containers."""
        self._listener = DockerListener(
            on_start=self._on_container_start,
            on_stop=self._on_container_stop,
            loop=asyncio.get_event_loop(),
        )

        if not DockerListener.docker_available():
            log.warning(
                "Docker socket not accessible. Event listener will not start. "
                "Ensure /var/run/docker.sock is mounted in this container."
            )
            return

        self._listener.start()
        await self._startup_sync()

    def cog_unload(self):
        """Stop the Docker event listener cleanly."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    async def _startup_sync(self):
        """On load, insert any recognized running containers not already tracked."""
        running = DockerListener.list_running_containers()
        all_guilds = await self.config.all_guilds()

        for guild_id, guild_data in all_guilds.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue

            channel_id = guild_data.get("channel_id")
            db_path = guild_data.get("db_path", _DEFAULT_DB_PATH)
            tracked = guild_data.get("tracked_rows", {})
            monitored = guild_data.get("monitored")

            if not channel_id:
                continue

            for name in running:
                if name in tracked:
                    continue  # Already tracking this one

                info = self._resolve_game_info(name, guild_data)
                if not info:
                    continue

                if monitored is not None and name not in monitored:
                    continue

                await self._insert_for_guild(guild, name, info, db_path, guild_data)

    def _resolve_game_info(self, container_name: str, guild_data: dict) -> dict | None:
        """Look up game info from game_map or guild custom mappings."""
        # Check custom mappings first (guild-specific overrides)
        custom = guild_data.get("custom_games", {})
        if container_name.lower() in {k.lower() for k in custom}:
            for k, v in custom.items():
                if k.lower() == container_name.lower():
                    return v
        return get_game_info(container_name)

    async def _insert_for_guild(self, guild, container_name: str, info: dict, db_path: str, guild_data: dict):
        """Insert a server row for a guild and track the row id."""
        channel_id = guild_data.get("channel_id")
        saved_styles = guild_data.get("saved_style_data", {})

        style_data = {**DEFAULT_STYLE_DATA}
        style_data["fullname"] = info.get("display_name", info.get("game_id", ""))
        if container_name in saved_styles:
            style_data.update(saved_styles[container_name])

        ip = DockerListener.get_container_ip(container_name)
        if not ip:
            log.warning("Could not get IP for container %s, skipping insert", container_name)
            return

        create_schema_if_missing(db_path)
        row_id = insert_server(db_path, {
            "guild_id": guild.id,
            "channel_id": channel_id,
            "game_id": info["game_id"],
            "address": ip,
            "query_port": info["query_port"],
            "query_extra": json.dumps(info.get("query_extra", {})),
            "style_data": json.dumps(style_data),
        })

        if row_id:
            async with self.config.guild(guild).tracked_rows() as tracked:
                tracked[container_name] = row_id
            log.info("Inserted row id=%s for container %s (guild %s)", row_id, container_name, guild.id)

    async def _on_container_start(self, container_name: str, container_id: str):
        """Called by DockerListener when a container starts."""
        all_guilds = await self.config.all_guilds()
        for guild_id, guild_data in all_guilds.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild or not guild_data.get("channel_id"):
                continue

            tracked = guild_data.get("tracked_rows", {})
            if container_name in tracked:
                continue  # Already tracked

            monitored = guild_data.get("monitored")
            if monitored is not None and container_name not in monitored:
                continue

            info = self._resolve_game_info(container_name, guild_data)
            if not info:
                continue

            db_path = guild_data.get("db_path", _DEFAULT_DB_PATH)
            await self._insert_for_guild(guild, container_name, info, db_path, guild_data)

    async def _on_container_stop(self, container_name: str, container_id: str):
        """Called by DockerListener when a container stops."""
        all_guilds = await self.config.all_guilds()
        for guild_id, guild_data in all_guilds.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue

            tracked = guild_data.get("tracked_rows", {})
            if container_name not in tracked:
                continue

            row_id = tracked[container_name]
            db_path = guild_data.get("db_path", _DEFAULT_DB_PATH)

            # Save current style_data before deleting
            row = get_server_by_id(db_path, row_id)
            if row and row.get("style_data"):
                try:
                    style = json.loads(row["style_data"])
                    async with self.config.guild(guild).saved_style_data() as saved:
                        saved[container_name] = style
                except (json.JSONDecodeError, TypeError):
                    pass

            delete_server_by_id(db_path, row_id)

            async with self.config.guild(guild).tracked_rows() as tracked_mut:
                tracked_mut.pop(container_name, None)

            log.info("Deleted row id=%s for container %s (guild %s)", row_id, container_name, guild.id)
```

- [ ] **Step 2: Commit**

```bash
git add gsm-autosync/gsm_autosync.py
git commit -m "feat: add main cog skeleton with Config registration and lifecycle hooks"
```

---

## Task 6: Setup Commands — channel, dbpath, list, addgame, removegame

**Files:**
- Modify: `gsm-autosync/gsm_autosync.py` — append command group

- [ ] **Step 1: Append the setup command group to `gsm_autosync.py`**

Add this after the `_on_container_stop` method inside the `GsmAutoSync` class:

```python
    # -------------------------------------------------------------------------
    # Setup commands
    # -------------------------------------------------------------------------

    @commands.group(name="gsmsetup")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def gsmsetup(self, ctx: commands.Context):
        """Configure the gsm-autosync cog."""

    @gsmsetup.command(name="channel")
    async def gsmsetup_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the Discord channel where DiscordGSM posts status cards."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"GSM channel set to {channel.mention}.")

    @gsmsetup.command(name="dbpath")
    async def gsmsetup_dbpath(self, ctx: commands.Context, path: str):
        """Override the default path to servers.db inside the container.

        Default: /discordgsm/servers.db
        """
        if not is_db_writable(path):
            await ctx.send(
                f"⚠️ Cannot write to `{path}`. Check the path and container mount. "
                "Path not saved."
            )
            return
        await self.config.guild(ctx.guild).db_path.set(path)
        await ctx.send(f"DB path set to `{path}`.")

    @gsmsetup.command(name="addgame")
    async def gsmsetup_addgame(
        self,
        ctx: commands.Context,
        container_name: str,
        game_id: str,
        query_port: int,
    ):
        """Manually map a container name to a DiscordGSM game_id and query port.

        Example: [p]gsmsetup addgame my-valheim-server valheim 2457
        """
        async with self.config.guild(ctx.guild).custom_games() as custom:
            custom[container_name.lower()] = {
                "game_id": game_id,
                "query_port": query_port,
                "display_name": container_name,
                "query_extra": {},
            }
        await ctx.send(
            f"Mapped `{container_name}` → game_id=`{game_id}`, port=`{query_port}`."
        )

    @gsmsetup.command(name="removegame")
    async def gsmsetup_removegame(self, ctx: commands.Context, container_name: str):
        """Remove a custom container mapping."""
        async with self.config.guild(ctx.guild).custom_games() as custom:
            if container_name.lower() not in custom:
                await ctx.send(f"`{container_name}` is not in custom mappings.")
                return
            del custom[container_name.lower()]
        await ctx.send(f"Removed custom mapping for `{container_name}`.")

    @gsmsetup.command(name="list")
    async def gsmsetup_list(self, ctx: commands.Context):
        """Show the current gsm-autosync configuration for this server."""
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data["channel_id"]) if data["channel_id"] else None
        tracked = data.get("tracked_rows", {})
        custom = data.get("custom_games", {})
        monitored = data.get("monitored")

        lines = [
            f"**Channel:** {channel.mention if channel else 'Not set'}",
            f"**DB Path:** `{data['db_path']}`",
            f"**Tracked containers:** {', '.join(f'`{k}`' for k in tracked) or 'none'}",
            f"**Custom mappings:** {', '.join(f'`{k}`' for k in custom) or 'none'}",
            f"**Monitored set:** {'all recognized' if monitored is None else ', '.join(f'`{m}`' for m in monitored)}",
        ]
        await ctx.send("\n".join(lines))

    @gsmsetup.command(name="status")
    async def gsmsetup_status(self, ctx: commands.Context):
        """Health check: Docker socket, DB path, and event listener."""
        data = await self.config.guild(ctx.guild).all()
        db_path = data["db_path"]

        docker_ok = DockerListener.docker_available()
        db_ok = is_db_writable(db_path)
        listener_ok = self._listener is not None and self._listener.is_connected

        lines = [
            f"{'✅' if docker_ok else '❌'} Docker socket: {'reachable' if docker_ok else 'NOT reachable — mount /var/run/docker.sock'}",
            f"{'✅' if db_ok else '❌'} DB at `{db_path}`: {'writable' if db_ok else 'NOT writable — check path and container mount'}",
            f"{'✅' if listener_ok else '❌'} Event listener: {'running' if listener_ok else 'not running'}",
        ]
        await ctx.send("\n".join(lines))
```

- [ ] **Step 2: Commit**

```bash
git add gsm-autosync/gsm_autosync.py
git commit -m "feat: add gsmsetup commands — channel, dbpath, addgame, removegame, list, status"
```

---

## Task 7: gsmsetup scan — Interactive Select Menu

**Files:**
- Modify: `gsm-autosync/gsm_autosync.py` — add View class and scan command

- [ ] **Step 1: Add the View class and scan command to `gsm_autosync.py`**

Add this class **before** the `GsmAutoSync` class definition:

```python
class ContainerSelectView(discord.ui.View):
    """Discord UI View for selecting which containers to monitor."""

    def __init__(self, containers: list[dict], guild_data: dict, timeout: float = 120):
        """
        containers: list of {name, known: bool, info: dict|None}
        guild_data: current guild config dict
        """
        super().__init__(timeout=timeout)
        self.containers = containers
        self.guild_data = guild_data
        self.confirmed = False
        self.selected_names: list[str] = []

        # Pre-select known containers
        default_selected = [c["name"] for c in containers if c["known"]]

        options = [
            discord.SelectOption(
                label=c["name"][:100],
                value=c["name"][:100],
                description=f"{'✅ ' + c['info']['game_id'] if c['known'] else '❓ unknown'}",
                default=c["name"] in default_selected,
            )
            for c in containers[:25]  # Discord select menu limit
        ]

        select = discord.ui.Select(
            placeholder="Select containers to monitor...",
            min_values=0,
            max_values=len(options),
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

        confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.green)
        confirm.callback = self._on_confirm
        self.add_item(confirm)

        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.red)
        cancel.callback = self._on_cancel
        self.add_item(cancel)

        self.selected_names = default_selected[:]

    async def _on_select(self, interaction: discord.Interaction):
        self.selected_names = interaction.data["values"]
        await interaction.response.defer()

    async def _on_confirm(self, interaction: discord.Interaction):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    async def _on_cancel(self, interaction: discord.Interaction):
        self.confirmed = False
        self.stop()
        await interaction.response.send_message("Scan cancelled.", ephemeral=True)
```

Then add this command to the `gsmsetup` group inside `GsmAutoSync`:

```python
    @gsmsetup.command(name="scan")
    async def gsmsetup_scan(self, ctx: commands.Context):
        """Interactively select which running containers to monitor.

        Shows all running containers. Known game containers are pre-selected.
        Select/deselect as desired, then confirm.
        """
        if not DockerListener.docker_available():
            await ctx.send("❌ Docker socket not reachable. Check your container setup.")
            return

        running = DockerListener.list_running_containers()
        if not running:
            await ctx.send("No running containers found.")
            return

        guild_data = await self.config.guild(ctx.guild).all()

        containers = []
        for name in running:
            info = self._resolve_game_info(name, guild_data)
            containers.append({"name": name, "known": info is not None, "info": info})

        # Build embed summary
        embed = discord.Embed(
            title="Docker Containers",
            description="Select which containers to monitor. Known game containers are pre-selected.",
            color=discord.Color.blurple(),
        )
        known = [c for c in containers if c["known"]]
        unknown = [c for c in containers if not c["known"]]
        if known:
            embed.add_field(
                name="✅ Known games",
                value="\n".join(f"`{c['name']}` ({c['info']['game_id']})" for c in known),
                inline=False,
            )
        if unknown:
            embed.add_field(
                name="❓ Unknown (will be ignored unless selected)",
                value="\n".join(f"`{c['name']}`" for c in unknown),
                inline=False,
            )

        view = ContainerSelectView(containers, guild_data)
        msg = await ctx.send(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            return

        selected = set(view.selected_names)

        # Prompt for game_id + port for any selected unknown containers
        custom_additions = {}
        for name in selected:
            info = self._resolve_game_info(name, guild_data)
            if info is None:
                await ctx.send(
                    f"Container `{name}` is unknown. What is the DiscordGSM `game_id`? "
                    f"(Reply within 30s, or type `skip` to ignore)"
                )
                try:
                    reply = await self.bot.wait_for(
                        "message",
                        timeout=30,
                        check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                    )
                    if reply.content.strip().lower() == "skip":
                        selected.discard(name)
                        continue
                    game_id = reply.content.strip()

                    await ctx.send(f"What is the query port for `{name}`?")
                    reply2 = await self.bot.wait_for(
                        "message",
                        timeout=30,
                        check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                    )
                    query_port = int(reply2.content.strip())
                    custom_additions[name.lower()] = {
                        "game_id": game_id,
                        "query_port": query_port,
                        "display_name": name,
                        "query_extra": {},
                    }
                except (asyncio.TimeoutError, ValueError):
                    await ctx.send(f"Skipping `{name}`.")
                    selected.discard(name)

        # Save custom additions
        if custom_additions:
            async with self.config.guild(ctx.guild).custom_games() as custom:
                custom.update(custom_additions)

        # Save monitored set
        await self.config.guild(ctx.guild).monitored.set(list(selected))

        db_path = guild_data["db_path"]
        channel_id = guild_data["channel_id"]
        if not channel_id:
            await ctx.send(
                "⚠️ No channel set. Run `[p]gsmsetup channel #your-channel` first, "
                "then run scan again."
            )
            return

        # Sync DB: insert selected running containers, remove deselected ones
        fresh_guild_data = await self.config.guild(ctx.guild).all()
        tracked = fresh_guild_data.get("tracked_rows", {})

        # Remove rows for deselected containers
        for name, row_id in list(tracked.items()):
            if name not in selected:
                delete_server_by_id(db_path, row_id)
                async with self.config.guild(ctx.guild).tracked_rows() as tr:
                    tr.pop(name, None)

        # Insert rows for selected containers not yet tracked
        for name in selected:
            if name in tracked:
                continue
            info = self._resolve_game_info(name, fresh_guild_data)
            if info:
                await self._insert_for_guild(
                    ctx.guild, name, info, db_path, fresh_guild_data
                )

        count = len(selected)
        await ctx.send(f"✅ Monitoring {count} container{'s' if count != 1 else ''}.")
```

- [ ] **Step 2: Commit**

```bash
git add gsm-autosync/gsm_autosync.py
git commit -m "feat: add gsmsetup scan with Discord select menu UI"
```

---

## Task 8: Push to GitHub

- [ ] **Step 1: Verify all files are staged correctly**

```bash
git status
```
Expected: working tree clean (all changes committed).

- [ ] **Step 2: Push to main**

```bash
git push -u origin main
```

- [ ] **Step 3: Verify on GitHub**

Visit https://github.com/emenblade/cogs and confirm the `gsm-autosync/` folder is present with all files.

---

## Manual Testing Checklist

After pushing, install on the bot and verify:

- [ ] `[p]load gsm-autosync` — cog loads without errors
- [ ] `[p]gsmsetup status` — shows Docker and DB status
- [ ] `[p]gsmsetup channel #channel` — sets channel
- [ ] `[p]gsmsetup scan` — shows dropdown with running containers
- [ ] Start a game server container → card appears in DiscordGSM channel after next poll
- [ ] Stop a game server container → card disappears
- [ ] Edit a card's style_data in DiscordGSM → stop/start container → style_data is preserved
- [ ] Manually added DiscordGSM entries are not touched by the cog
- [ ] `[p]gsmsetup list` — shows correct config
