# Red Bot Cog — DiscordGSM Auto-Sync
## Project Context for Claude Code

---

## What We're Building

A **Red-DiscordBot cog** that watches Docker for game server containers starting/stopping on an Unraid NAS, then automatically adds/removes them from DiscordGSM's SQLite database so the status cards appear in Discord without manual setup.

---

## The Stack

- **Unraid 6.12.10** home lab (NAS + Docker host)
- **Red-DiscordBot** running in Docker container (`red-discordbot`)
- **DiscordGSM** running in Docker container (`DiscordGSM`) — posts game server status cards to Discord
- **DiscordGSM database**: SQLite at `servers.db` (path on Unraid TBD — Alex has edited it before via a SQL web tool)

---

## DiscordGSM Database Schema

```sql
CREATE TABLE servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position INT NOT NULL,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT,          -- DiscordGSM fills this in after posting
    game_id TEXT NOT NULL,       -- DiscordGSM's internal game identifier string
    address TEXT NOT NULL,       -- Docker bridge IP of the game container
    query_port INT(5) NOT NULL,  -- Game query port
    query_extra TEXT NOT NULL,   -- Usually '{}'
    status INT(1) NOT NULL,
    result TEXT NOT NULL,        -- JSON, DiscordGSM fills this in
    style_id TEXT NOT NULL,      -- e.g. 'Large'
    style_data TEXT NOT NULL     -- JSON: fullname, description, image_url, etc.
)
```

**Current live entry example (Minecraft):**
```
id=23, position=0
game_id: minecraft
address: 172.17.0.10
query_port: 25565
query_extra: {}
style_id: Large
style_data: {
  "fullname": "Minecraft (2009)",
  "locale": "en-US",
  "description": "This is the server for the streamers-r-us community.",
  "image_url": "",
  "thumbnail_url": "https://192-168-1-10.ae8eaff57b29fb307b904127b1627c45385aa632.myunraid.net/state/plugins/dynamix.docker.manager/images/binhex-minecraftserver-icon.png?...",
  "country": "Ca"
}
```

**Discord IDs (from existing entry):**
- `guild_id`: `1174951012474310697`
- `channel_id`: `1174952379423129651` ← confirm if new cards should go here too

---

## Game Servers Currently on the Unraid Stack

All currently **stopped** in Docker. Need to map each to DiscordGSM's `game_id` string + query port:

| Container Name       | Likely game_id       | Default Query Port |
|----------------------|----------------------|--------------------|
| Satisfactory         | `satisfactory`       | 15777              |
| V-Rising             | `vrising`            | 9877               |
| CoreKeeper           | `corekeeper`         | 27016 (Steam)      |
| DontStarveTogether   | `dontstarvetogether` | 27016              |
| Valheim              | `valheim`            | 2457               |
| MinecraftBasicServer | `minecraft`          | 25565              |
| binhex-minecraftserver | `minecraft`        | 25565              |
| Minecraft-forge      | `minecraft`          | 25565              |

> ⚠️ These game_id strings and ports need to be verified against DiscordGSM's supported games list: https://github.com/discordgsm/discordgsm-docs

---

## How the Cog Should Work

1. **On cog load** — scan Docker for running game server containers, sync any missing ones into `servers.db`
2. **Docker event listener** — watch for `container start` / `container stop` events
3. **On container start** — look up game type from container name → INSERT row into `servers.db`
4. **On container stop** — DELETE corresponding row from `servers.db`
5. **DiscordGSM refresh** — it polls on its own timer, but optionally poke its HTTP API if one exists

### Docker Access
- Need to confirm: does `red-discordbot` container have `/var/run/docker.sock` mounted?
- If not, it needs to be added in Unraid's container config (Extra Parameters: `-v /var/run/docker.sock:/var/run/docker.sock`)
- Will use the `docker` Python SDK inside the cog

### DB Access
- `servers.db` needs to be mounted/accessible inside the Red bot container
- Or: cog runs docker exec / writes via shared Unraid path
- Need the actual path on the Unraid filesystem (e.g. `/mnt/user/appdata/discordgsm/servers.db`)

---

## Red Bot Cog Structure

```
gsm-autosync/
├── __init__.py
├── gsm_autosync.py      # Main cog
├── game_map.py          # Container name → game_id + port lookup table
├── requirements.txt     # docker (Python SDK)
└── info.json            # Red cog metadata
```

---

## Confirmed Setup Details

1. **Docker socket**: NOT currently mounted in `red-discordbot`. First step of setup is adding `-v /var/run/docker.sock:/var/run/docker.sock` to the container's Extra Parameters in Unraid, then restarting it.
2. **servers.db path**: Confirmed at `/mnt/user/appdata/discordgsm/servers.db`
3. **Channel**: `1174952379423129651` is correct for this server, BUT — see Multi-Server Design below.
4. **On container stop**: DELETE the row (cards disappear when server goes down).
5. **Exclusions**: Cog should have a configurable ignore list — not every container is a game server.

---

## Multi-Server Design (Important)

Alex runs **3 different Discord servers, each with their own Red bot instance**. The cog must be fully self-contained and configurable per-guild via Red commands. No hardcoded IDs anywhere.

### Required Setup Commands

The cog should ship with a setup flow, something like:

```
[p]gsmsetup channel #game-servers     — set which channel GSM cards post to
[p]gsmsetup dbpath /path/to/servers.db — path to DiscordGSM's SQLite DB
[p]gsmsetup addgame <container_name> <game_id> <query_port>  — manually map a container
[p]gsmsetup ignore <container_name>   — exclude a container from auto-detection
[p]gsmsetup list                      — show current config
[p]gsmsetup test                      — scan Docker now and show what would be added
```

Settings stored in Red's Config system (per-guild), not hardcoded.

---

## Repo Setup

- New GitHub repo: suggest name `red-gsm-autosync` or `red-cog-gsm-autosync`
- Should follow Red-DiscordBot cog packaging conventions
- Include a `README.md` with install instructions (repo add + cog install commands)

---

## Dev Environment Notes

- Alex uses **Unraid** — appdata typically at `/mnt/user/appdata/`
- Red bot likely at `/mnt/user/appdata/red-discordbot/`
- DiscordGSM appdata likely at `/mnt/user/appdata/discordgsm/`
- Alex's online alias: **emenblade**
