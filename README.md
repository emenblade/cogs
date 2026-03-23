# cogs — emenblade's Red-DiscordBot Cogs

## Forms

Discord-native support tickets and application forms, driven entirely by buttons, dropdowns, and modals. No commands required from end users.

**Features:**
- 7-step setup wizard
- Private ticket channels with category selection, staff-only close, and full transcripts
- Application builder — create multi-question forms via DM, post Apply buttons to any channel
- Staff review forum with Approve/Deny buttons, automatic role assignment, and re-application cooldowns
- Persistent views survive bot restarts
- Slash command support (`/forms setup`, `/forms settings`)

### Install

```
[p]repo add cogs https://github.com/emenblade/cogs
[p]cog install cogs forms
[p]load forms
[p]forms setup
```

### Commands

| Command | Who | Description |
|---|---|---|
| `/forms setup` | Admins | Run the first-time 7-step setup wizard |
| `/forms settings` | Staff / Admins | Open the settings panel to manage tickets and applications |

### Documentation

- **[User Guide](https://blog.emen.win/Forms-cog-user-guide.html)** — step-by-step walkthrough for server members, including troubleshooting
- **[Technical Reference](docs/TECHNICAL.md)** — architecture, config schema, flow diagrams, timeout reference

---

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
