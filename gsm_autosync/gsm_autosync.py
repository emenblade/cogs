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
from .game_map import get_game_info

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


class ContainerSelectView(discord.ui.View):
    """Discord UI View for selecting which containers to monitor."""

    def __init__(self, containers: list[dict], guild_data: dict, invoking_user: discord.Member, timeout: float = 120):
        """
        containers: list of {name, known: bool, info: dict|None}
        guild_data: current guild config dict
        """
        super().__init__(timeout=timeout)
        self.invoking_user = invoking_user
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.invoking_user:
            await interaction.response.send_message(
                "Only the person who ran this command can use this menu.", ephemeral=True
            )
            return False
        return True


class GsmAutoSync(commands.Cog):
    """Auto-sync game server containers to DiscordGSM."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8675309420, force_registration=True)

        self.config.register_guild(
            channel_id=None,          # Discord channel for GSM cards
            admin_channel_id=None,    # Discord channel for cog notifications (defaults to channel_id)
            connect_host=None,        # Hostname/IP for player connect address (e.g. game.emen.win)
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
            loop=asyncio.get_running_loop(),
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

        exposed_ports = DockerListener.get_container_exposed_ports(container_name)
        if exposed_ports and info["query_port"] not in exposed_ports:
            log.info(
                "Container %s does not expose port %s (exposed: %s), skipping insert",
                container_name, info["query_port"], exposed_ports,
            )
            return

        ip = DockerListener.get_container_ip(container_name)
        if not ip:
            log.warning("Could not get IP for container %s, skipping insert", container_name)
            return
        address = ip
        query_port = info["query_port"]

        # Always include password in query_extra — DiscordGSM's /refresh requires it
        query_extra = dict(info.get("query_extra", {}))
        query_extra.setdefault("password", "")

        create_schema_if_missing(db_path)
        row_id = insert_server(db_path, {
            "guild_id": guild.id,
            "channel_id": channel_id,
            "game_id": info["game_id"],
            "address": address,
            "query_port": query_port,
            "query_extra": json.dumps(query_extra),
            "style_data": json.dumps(style_data),
        })

        if row_id:
            async with self.config.guild(guild).tracked_rows() as tracked:
                tracked[container_name] = row_id
            log.info("Inserted row id=%s for container %s (guild %s)", row_id, container_name, guild.id)
            admin_ch_id = guild_data.get("admin_channel_id") or channel_id
            admin_ch = guild.get_channel(admin_ch_id)
            if admin_ch:
                await admin_ch.send(
                    f"🟢 `{container_name}` detected — added to DiscordGSM. Run `/refresh` to generate the card."
                )

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
            admin_ch_id = guild_data.get("admin_channel_id") or guild_data.get("channel_id")
            admin_ch = guild.get_channel(admin_ch_id)
            if admin_ch:
                await admin_ch.send(
                    f"🔴 `{container_name}` stopped — removed from DiscordGSM."
                )

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

    @gsmsetup.command(name="adminchannel")
    async def gsmsetup_adminchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where the cog posts notifications (container start/stop).

        Defaults to the GSM cards channel if not set.
        """
        await self.config.guild(ctx.guild).admin_channel_id.set(channel.id)
        await ctx.send(f"Admin notifications channel set to {channel.mention}.")

    @gsmsetup.command(name="connecthost")
    async def gsmsetup_connecthost(self, ctx: commands.Context, hostname: str = None):
        """Set the hostname players use to connect (e.g. game.emen.win).

        When set, the cog uses this hostname + the container's host-mapped port
        as the query address instead of the internal bridge IP.
        Run without arguments to clear.
        """
        await self.config.guild(ctx.guild).connect_host.set(hostname or None)
        if hostname:
            await ctx.send(f"Connect host set to `{hostname}`.")
        else:
            await ctx.send("Connect host cleared — will use bridge IP for queries.")

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
        admin_ch = ctx.guild.get_channel(data["admin_channel_id"]) if data.get("admin_channel_id") else None
        tracked = data.get("tracked_rows", {})
        custom = data.get("custom_games", {})
        monitored = data.get("monitored")

        lines = [
            f"**GSM Channel:** {channel.mention if channel else 'Not set'}",
            f"**Admin Channel:** {admin_ch.mention if admin_ch else f'Not set (defaults to GSM channel)'}",
            f"**Connect Host:** `{data.get('connect_host') or 'Not set (uses bridge IP)'}` ",
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
            f"{'✅' if docker_ok else '❌'} Docker socket: {'reachable' if docker_ok else 'NOT reachable — ensure /var/run/docker.sock is mounted and run `chmod 666 /var/run/docker.sock` on the host'}",
            f"{'✅' if db_ok else '❌'} DB at `{db_path}`: {'writable' if db_ok else 'NOT writable — check path and container mount'}",
            f"{'✅' if listener_ok else '❌'} Event listener: {'running' if listener_ok else 'not running'}",
        ]
        await ctx.send("\n".join(lines))

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

        view = ContainerSelectView(containers, guild_data, invoking_user=ctx.author)
        await ctx.send(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            return

        selected = set(view.selected_names)

        # Prompt for game_id + port for any selected unknown containers
        custom_additions = {}
        for name in list(selected):
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
                # Save style_data before deleting (preserves user edits)
                row = get_server_by_id(db_path, row_id)
                if row and row.get("style_data"):
                    try:
                        style = json.loads(row["style_data"])
                        async with self.config.guild(ctx.guild).saved_style_data() as saved:
                            saved[name] = style
                    except (json.JSONDecodeError, TypeError):
                        pass
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
