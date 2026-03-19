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
