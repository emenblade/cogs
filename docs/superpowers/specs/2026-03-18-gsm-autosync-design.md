# gsm-autosync — Design Spec
*Date: 2026-03-18*

---

## Overview

A Red-DiscordBot cog that watches Docker for game server containers starting and stopping on an Unraid NAS, then automatically adds and removes them from DiscordGSM's SQLite database (`servers.db`) so status cards appear in Discord without manual setup.

---

## File Structure

```
gsm-autosync/
├── __init__.py         # async setup(bot) — registers the cog
├── gsm_autosync.py     # Main cog: Docker listener, DB writes, setup commands
├── game_map.py         # Static lookup: container name → game_id, query_port, display name
├── info.json           # Red metadata, declares `docker` pip requirement
└── requirements.txt    # docker
```

---

## Architecture

### Docker Event Listener (Streaming)

The Docker Python SDK's `events()` generator streams container events in real time. This runs in a background thread via `asyncio.run_in_executor` to avoid blocking the bot's event loop. When a `start` or `die`/`stop` event arrives, it wakes the async side to perform the DB write.

- Started in `cog_load()`
- Shut down in `cog_unload()` by calling `docker_client.close()`, which unblocks the `events()` generator and allows the thread to exit cleanly — no leaked threads
- Falls back gracefully if Docker socket is not accessible (logs warning, cog still loads, event listener not started)

### Whitelist Logic

The cog **only acts on containers it recognizes**. Unknown container names are silently ignored — no ignore list needed.

Recognition priority:
1. `game_map.py` default entries (matched case-insensitively)
2. Custom mappings stored in Red Config per guild (added via `[p]gsmsetup addgame` or the scan flow)

### Row Ownership Tracking

The cog only manages rows it created. When a row is inserted, its `id` is saved to Red Config (per guild, keyed by container name). On container stop, only the tracked row ID is deleted — never any row the cog didn't create. Manually added DiscordGSM entries are completely invisible to the cog and will never be touched.

### DB Path Resolution

Priority chain (first match wins):
1. `GSM_DB_PATH` environment variable
2. `/discordgsm/servers.db` — default, works out of the box with the provided XML template
3. User override via `[p]gsmsetup dbpath`

### Network / Address

DiscordGSM and game server containers run on the same Docker bridge network. The `address` field uses the game container's Docker bridge IP (e.g., `172.17.0.x`), consistent with the existing live DiscordGSM entry. Retrieved via Docker inspect at container start time.

---

## Data Flow

### On Cog Load
1. Read Config (channel, DB path, custom mappings, monitored set, tracked row IDs, saved style_data)
2. Connect to Docker socket
3. Scan running containers → for each recognized container not already tracked in Config, insert and track
4. Start Docker event stream thread

### On Container Start
1. Receive `start` event from stream
2. Look up container name in monitored set (game_map + custom mappings), case-insensitive
3. If not recognized → skip silently
4. Get container's Docker bridge IP via inspect
5. Check tracked row IDs in Config — skip if already tracking this container (prevents duplicate inserts on restart)
6. Load saved `style_data` from Config if it exists (user's prior edits), otherwise use game_map defaults
7. Insert row into `servers.db` inside a transaction (position assignment + insert are atomic)
8. Save returned row `id` to Red Config keyed by container name
9. Log success

### On Container Stop
1. Receive `die` or `stop` event from stream
2. Look up container name in monitored set
3. If not recognized → skip silently
4. Look up tracked row ID for this container from Red Config
5. If no tracked ID → skip (row not owned by cog)
6. Save the row's current `style_data` to Red Config (keyed by container name) before deleting — preserves any user edits
7. Delete row by tracked `id`
8. Remove tracked row ID from Config
9. Log success

### On Cog Unload
1. Call `docker_client.close()` to unblock the event stream generator
2. Join the thread with a short timeout (e.g. `thread.join(timeout=5)`) before returning, to avoid a window where two threads hold DB handles during a cog reload

---

## servers.db Insert Schema

| Field | Value |
|---|---|
| `position` | Assigned inside a transaction: `SELECT MAX(position) + 1 FROM servers` then INSERT — serialized per guild to avoid race conditions |
| `guild_id` | From Red Config (set via `[p]gsmsetup channel`) |
| `channel_id` | From Red Config (set via `[p]gsmsetup channel`) |
| `message_id` | `NULL` — DiscordGSM detects NULL rows on its next poll, posts the Discord message, and updates this field itself |
| `game_id` | From game_map or custom mapping |
| `address` | Container's Docker bridge IP |
| `query_port` | From game_map or custom mapping |
| `query_extra` | See game_map — most games use `{}`, exceptions noted below |
| `status` | `1` |
| `result` | `{}` — DiscordGSM fills this in after first poll |
| `style_id` | `Large` (confirmed from live DiscordGSM entry) |
| `style_data` | See below |

### style_data defaults
```json
{
  "fullname": "<display name from game_map>",
  "locale": "en-US",
  "description": "",
  "image_url": "",
  "thumbnail_url": "",
  "country": "CA"
}
```

### Known Limitation
After a row is inserted, the status card will not appear in Discord until DiscordGSM's next poll cycle. This is expected behavior — DiscordGSM owns the Discord message lifecycle.

---

## Setup Commands

All commands require `manage_guild` permission. All settings stored per-guild in Red's Config system. Every command operates on the invoking guild's config only.

| Command | Description |
|---|---|
| `[p]gsmsetup channel #channel` | Set the Discord channel for GSM cards |
| `[p]gsmsetup dbpath /path/to/db` | Override the default servers.db path |
| `[p]gsmsetup addgame <name> <game_id> <port>` | Manually map a container name |
| `[p]gsmsetup removegame <name>` | Remove a custom container mapping |
| `[p]gsmsetup list` | Show full current config |
| `[p]gsmsetup scan` | Interactive container selection (see below) |
| `[p]gsmsetup status` | Health check: Docker socket reachable, DB path writable, event thread alive |

### `[p]gsmsetup scan` — Interactive Setup Flow

1. Bot queries Docker for all currently running containers
2. Posts embed listing each container tagged `✅ known game` or `❓ unknown`
3. Renders a Discord Select Menu (multi-select dropdown) with all containers:
   - Known game containers are **pre-selected**
   - Unknown containers are **unselected by default**
4. User selects/deselects desired containers and confirms
5. For any **unknown** containers the user selects: bot prompts for `game_id` and `query_port` in sequence
6. Selected set saved to invoking guild's Config as the monitored set
7. `servers.db` is immediately synced: insert missing rows, delete rows for deselected servers

---

## game_map.py — Default Container Mappings

> ⚠️ This list was hand-assembled from the user's known container names. All `game_id` strings and `query_port` values must be verified against DiscordGSM's official supported games list before use — they are not pulled from DiscordGSM automatically.

| Container Name | game_id | query_port | query_extra | Display Name |
|---|---|---|---|---|
| `Satisfactory` | `satisfactory` | `15777` | `{}` | Satisfactory |
| `V-Rising` | `vrising` | `9877` | `{}` | V Rising |
| `CoreKeeper` | `corekeeper` | `27016` | `{}` | Core Keeper |
| `DontStarveTogether` | `dontstarvetogether` | `27016` | `{}` | Don't Starve Together |
| `Valheim` | `valheim` | `2457` | `{}` | Valheim |
| `MinecraftBasicServer` | `minecraft` | `25565` | `{}` | Minecraft |
| `binhex-minecraftserver` | `minecraft` | `25565` | `{}` | Minecraft |
| `Minecraft-forge` | `minecraft` | `25565` | `{}` | Minecraft (Forge) |

---

## Error Handling

- All errors logged via Red's logging system (visible via `[p]logs`)
- Cog loads successfully even if Docker socket is inaccessible (logs warning, event listener not started)
- DB write failures caught and logged without crashing the cog
- Future: `[p]gsmsetup alertchannel #channel` for posting errors to Discord

---

## Multi-Guild Support

All settings (channel, DB path, custom mappings, monitored set) are stored per-guild in Red's Config system. No hardcoded IDs. Each guild runs its own independent configuration. All commands scope to the invoking guild via `ctx.guild`.

---

## SQLite Concurrency & File Permissions

DiscordGSM writes to `servers.db` on its own poll cycle. To avoid `SQLITE_BUSY` errors:
- Open connections with `timeout=10` (sqlite3 default is 5s)
- Catch `sqlite3.OperationalError` on all DB operations and log — do not crash
- All inserts wrapped in transactions as described above

**File permissions:** Both containers mount the same host path (`/mnt/user/appdata/discordgsm`). On Unraid, appdata files are typically owned by `nobody:users` (99:100). The Red bot container runs as `PUID=99 PGID=100` by default, so write access should work out of the box. `[p]gsmsetup status` will explicitly verify that the DB path is writable at runtime.

---

## Dependencies

- `docker` — Python Docker SDK (declared in `info.json` `requirements` field and `requirements.txt`)
- `discord.py` 2.x — Select Menu UI components (bundled with Red 3.5)
- `sqlite3` — stdlib

---

## Unraid Setup Prerequisites

1. Mount Docker socket in `red-discordbot` container: `-v /var/run/docker.sock:/var/run/docker.sock` (included in provided XML template)
2. Mount DiscordGSM appdata: `/mnt/user/appdata/discordgsm` → `/discordgsm` (included in provided XML template)
3. Install cog:
   ```
   [p]repo add cogs https://github.com/emenblade/cogs
   [p]cog install cogs gsm-autosync
   ```
4. `[p]gsmsetup channel #your-channel`
5. `[p]gsmsetup scan` — select your servers
6. Run `[p]gsmsetup status` to verify everything is connected
