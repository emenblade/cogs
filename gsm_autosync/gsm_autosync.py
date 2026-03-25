"""gsm-autosync — Main cog.

Watches Docker events and syncs game server containers into DiscordGSM's
servers.db automatically. Supports smart detection of unknown containers
with a persistent Accept/Reject prompt in the admin channel.
"""

import asyncio
import json
import logging
import os
import uuid

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red

from .db import (
    create_schema_if_missing,
    delete_server_by_id,
    get_server_by_id,
    insert_server,
    is_db_writable,
    update_server_message_id,
)
from .docker_listener import DockerListener
from .game_map import get_game_info
from .games_loader import fuzzy_match, load_games_csv

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


class GameDetectionView(discord.ui.View):
    """Persistent Accept/Reject prompt for auto-detected game containers.

    timeout=None means buttons never expire — they'll live until the bot restarts.
    """

    def __init__(self, cog: "GsmAutoSync", detection_id: str, candidates: list):
        super().__init__(timeout=None)
        self.cog = cog
        self.detection_id = detection_id

        for i, (game_id, info, confidence) in enumerate(candidates):
            label = f"{info['name'][:35]} ({confidence:.0%})"
            btn = discord.ui.Button(
                label=label,
                custom_id=f"gsm_det_{detection_id}_{i}",
                style=discord.ButtonStyle.green if i == 0 else discord.ButtonStyle.secondary,
                row=0,
            )
            btn.callback = self._make_accept(i)
            self.add_item(btn)

        reject = discord.ui.Button(
            label="None of these",
            custom_id=f"gsm_det_{detection_id}_r",
            style=discord.ButtonStyle.red,
            row=1,
        )
        reject.callback = self._on_reject
        self.add_item(reject)

    def _make_accept(self, idx: int):
        async def callback(interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "You need Manage Server permission.", ephemeral=True
                )
                return
            await self.cog._on_detection_accepted(interaction, self.detection_id, idx)
            self.stop()
        return callback

    async def _on_reject(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "You need Manage Server permission.", ephemeral=True
            )
            return
        await self.cog._on_detection_rejected(interaction, self.detection_id)
        self.stop()


class ContainerSelectView(discord.ui.View):
    """Discord UI View for selecting which containers to monitor."""

    def __init__(
        self,
        containers: list[dict],
        guild_data: dict,
        invoking_user: discord.Member,
        timeout: float = 120,
    ):
        super().__init__(timeout=timeout)
        self.invoking_user = invoking_user
        self.containers = containers
        self.guild_data = guild_data
        self.confirmed = False
        self.selected_names: list[str] = []

        default_selected = [c["name"] for c in containers if c["known"]]

        options = [
            discord.SelectOption(
                label=c["name"][:100],
                value=c["name"][:100],
                description=f"{'✅ ' + c['info']['game_id'] if c['known'] else '❓ unknown'}",
                default=c["name"] in default_selected,
            )
            for c in containers[:25]
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
            channel_id=None,
            admin_channel_id=None,
            connect_host=None,
            db_path=_DEFAULT_DB_PATH,
            custom_games={},
            monitored=None,
            tracked_rows={},
            saved_style_data={},
        )
        self._listener: DockerListener | None = None
        self._pending_detections: dict[str, dict] = {}
        self._games_cache: dict = {}

    async def cog_load(self):
        """Start Docker event listener, load games cache, and sync running containers."""
        self._games_cache = load_games_csv()

        self._listener = DockerListener(
            on_start=self._on_container_start,
            on_stop=self._on_container_stop,
            loop=asyncio.get_running_loop(),
        )

        if not DockerListener.docker_available():
            log.warning(
                "Docker socket not accessible. Event listener will not start. "
                "Ensure /var/run/docker.sock is mounted and run chmod 666 /var/run/docker.sock."
            )
            return

        self._listener.start()
        await self._startup_sync()

    def cog_unload(self):
        """Stop the Docker event listener cleanly."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

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
                    continue

                info = self._resolve_game_info(name, guild_data)
                if not info:
                    continue

                if monitored is not None and name not in monitored:
                    continue

                await self._insert_for_guild(guild, name, info, db_path, guild_data)

    def _resolve_game_info(self, container_name: str, guild_data: dict) -> dict | None:
        """Look up game info from custom_games or the static game_map."""
        custom = guild_data.get("custom_games", {})
        if container_name.lower() in {k.lower() for k in custom}:
            for k, v in custom.items():
                if k.lower() == container_name.lower():
                    return v
        return get_game_info(container_name)

    async def _insert_for_guild(
        self,
        guild: discord.Guild,
        container_name: str,
        info: dict,
        db_path: str,
        guild_data: dict,
    ):
        """Insert a server row, send a placeholder message for DiscordGSM, and track the row."""
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
                container_name,
                info["query_port"],
                exposed_ports,
            )
            return

        ip = DockerListener.get_container_ip(container_name)
        if not ip:
            log.warning("Could not get IP for container %s, skipping insert", container_name)
            return

        query_extra = dict(info.get("query_extra", {}))
        query_extra.setdefault("password", "")

        create_schema_if_missing(db_path)
        row_id = insert_server(
            db_path,
            {
                "guild_id": guild.id,
                "channel_id": channel_id,
                "game_id": info["game_id"],
                "address": ip,
                "query_port": info["query_port"],
                "query_extra": json.dumps(query_extra),
                "style_data": json.dumps(style_data),
            },
        )

        if not row_id:
            return

        async with self.config.guild(guild).tracked_rows() as tracked:
            tracked[container_name] = row_id

        log.info("Inserted row id=%s for container %s (guild %s)", row_id, container_name, guild.id)

        # Send a placeholder embed to the GSM channel.
        # DiscordGSM's background task (runs every ~15s) will see the message_id
        # and replace this placeholder with the real server status card.
        gsm_ch = guild.get_channel(channel_id)
        if gsm_ch:
            try:
                placeholder = discord.Embed(
                    title=f"⏳ {style_data['fullname']}",
                    description="Fetching server status...",
                    color=discord.Color.from_rgb(44, 47, 51),
                )
                msg = await gsm_ch.send(embed=placeholder)
                update_server_message_id(db_path, row_id, msg.id)
            except Exception as e:
                log.warning("Could not send placeholder for %s: %s", container_name, e)

        admin_ch_id = guild_data.get("admin_channel_id") or channel_id
        admin_ch = guild.get_channel(admin_ch_id)
        if admin_ch:
            await admin_ch.send(
                f"🟢 `{container_name}` detected — added to DiscordGSM. Card will appear within ~15s."
            )

    async def _handle_smart_detection(
        self,
        guild: discord.Guild,
        container_name: str,
        db_path: str,
        guild_data: dict,
    ):
        """Try to identify an unknown container via fuzzy match and prompt admin."""
        exposed_ports = DockerListener.get_container_exposed_ports(container_name)

        if not self._games_cache:
            self._games_cache = load_games_csv()

        candidates = fuzzy_match(container_name, exposed_ports, self._games_cache)

        admin_ch_id = guild_data.get("admin_channel_id") or guild_data.get("channel_id")
        admin_ch = guild.get_channel(admin_ch_id)
        if not admin_ch:
            return

        if not candidates:
            await admin_ch.send(
                f"❓ `{container_name}` started but didn't match any DiscordGSM game. "
                f"Use `/gsm addgame` to map it manually."
            )
            return

        detection_id = uuid.uuid4().hex[:8]
        self._pending_detections[detection_id] = {
            "guild": guild,
            "container_name": container_name,
            "candidates": candidates,
            "db_path": db_path,
            "guild_data": guild_data,
        }

        ports_str = ", ".join(str(p) for p in sorted(exposed_ports)) if exposed_ports else "none"

        embed = discord.Embed(
            title=f"🔍 Unknown container: `{container_name}`",
            description="Could not auto-identify. Top matches from DiscordGSM game list:",
            color=discord.Color.yellow(),
        )
        embed.add_field(name="Exposed ports", value=f"`{ports_str}`", inline=False)

        for i, (game_id, info, confidence) in enumerate(candidates):
            qport = info.get("query_port")
            port_match = " ✅" if qport and qport in exposed_ports else ""
            embed.add_field(
                name=f"#{i + 1} {info['name']}{port_match}",
                value=f"`{game_id}` | query port: `{qport or '?'}`\nConfidence: {confidence:.0%}",
                inline=False,
            )

        view = GameDetectionView(self, detection_id, candidates)
        await admin_ch.send(embed=embed, view=view)

    async def _on_detection_accepted(
        self, interaction: discord.Interaction, detection_id: str, idx: int
    ):
        pending = self._pending_detections.pop(detection_id, None)
        if not pending:
            await interaction.response.send_message(
                "This detection has already been handled.", ephemeral=True
            )
            return

        game_id, info, _ = pending["candidates"][idx]
        game_info = {
            "game_id": game_id,
            "query_port": info["query_port"],
            "display_name": info["name"],
            "query_extra": {},
        }

        # Save as custom game so it's remembered on future starts
        async with self.config.guild(pending["guild"]).custom_games() as custom:
            custom[pending["container_name"].lower()] = game_info

        await self._insert_for_guild(
            pending["guild"],
            pending["container_name"],
            game_info,
            pending["db_path"],
            pending["guild_data"],
        )

        await interaction.response.send_message(
            f"✅ Mapped `{pending['container_name']}` as **{info['name']}** and added to DiscordGSM.",
            ephemeral=True,
        )
        await interaction.message.edit(view=None)

    async def _on_detection_rejected(
        self, interaction: discord.Interaction, detection_id: str
    ):
        pending = self._pending_detections.pop(detection_id, None)
        container_name = pending["container_name"] if pending else "container"
        await interaction.response.send_message(
            f"❌ Rejected. `{container_name}` will not be tracked. "
            f"Use `/gsm addgame` to map it manually.",
            ephemeral=True,
        )
        await interaction.message.edit(view=None)

    async def _on_container_start(self, container_name: str, container_id: str):
        """Called by DockerListener when a container starts."""
        all_guilds = await self.config.all_guilds()
        for guild_id, guild_data in all_guilds.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild or not guild_data.get("channel_id"):
                continue

            tracked = guild_data.get("tracked_rows", {})
            if container_name in tracked:
                continue

            monitored = guild_data.get("monitored")
            if monitored is not None and container_name not in monitored:
                continue

            db_path = guild_data.get("db_path", _DEFAULT_DB_PATH)
            info = self._resolve_game_info(container_name, guild_data)

            if info:
                await self._insert_for_guild(guild, container_name, info, db_path, guild_data)
            else:
                # Unknown container — try smart detection
                await self._handle_smart_detection(guild, container_name, db_path, guild_data)

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
                await admin_ch.send(f"🔴 `{container_name}` stopped — removed from DiscordGSM.")

    # -------------------------------------------------------------------------
    # Commands — hybrid: work as both /gsm ... and !gsm ...
    # Run [p]slash sync after loading to register slash commands with Discord.
    # -------------------------------------------------------------------------

    @commands.hybrid_group(name="gsm")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def gsm(self, ctx: commands.Context):
        """Configure and manage gsm-autosync."""

    @gsm.command(name="channel")
    @app_commands.describe(channel="Channel where DiscordGSM posts status cards")
    async def gsm_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the Discord channel where DiscordGSM posts status cards."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"GSM channel set to {channel.mention}.", ephemeral=True)

    @gsm.command(name="adminchannel")
    @app_commands.describe(channel="Channel for cog notifications (container start/stop)")
    async def gsm_adminchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where the cog posts container start/stop notifications."""
        await self.config.guild(ctx.guild).admin_channel_id.set(channel.id)
        await ctx.send(f"Admin notifications channel set to {channel.mention}.", ephemeral=True)

    @gsm.command(name="connecthost")
    @app_commands.describe(hostname="Hostname players use to connect, e.g. game.emen.win. Leave blank to clear.")
    async def gsm_connecthost(self, ctx: commands.Context, hostname: str = None):
        """Set the hostname players use to connect. Leave blank to clear."""
        await self.config.guild(ctx.guild).connect_host.set(hostname or None)
        if hostname:
            await ctx.send(f"Connect host set to `{hostname}`.", ephemeral=True)
        else:
            await ctx.send("Connect host cleared — will use bridge IP.", ephemeral=True)

    @gsm.command(name="dbpath")
    @app_commands.describe(path="Path to servers.db inside the container. Default: /discordgsm/servers.db")
    async def gsm_dbpath(self, ctx: commands.Context, path: str):
        """Override the default path to servers.db."""
        if not is_db_writable(path):
            await ctx.send(
                f"⚠️ Cannot write to `{path}`. Check the path and container mount. Not saved.",
                ephemeral=True,
            )
            return
        await self.config.guild(ctx.guild).db_path.set(path)
        await ctx.send(f"DB path set to `{path}`.", ephemeral=True)

    @gsm.command(name="addgame")
    @app_commands.describe(
        container_name="Docker container name",
        game_id="DiscordGSM game_id (e.g. minecraft, valheim)",
        query_port="Query port for the game server",
    )
    async def gsm_addgame(
        self, ctx: commands.Context, container_name: str, game_id: str, query_port: int
    ):
        """Manually map a container to a DiscordGSM game_id and query port."""
        async with self.config.guild(ctx.guild).custom_games() as custom:
            custom[container_name.lower()] = {
                "game_id": game_id,
                "query_port": query_port,
                "display_name": container_name,
                "query_extra": {},
            }
        await ctx.send(
            f"Mapped `{container_name}` → `{game_id}` port `{query_port}`.", ephemeral=True
        )

    @gsm.command(name="removegame")
    @app_commands.describe(container_name="Docker container name to remove from custom mappings")
    async def gsm_removegame(self, ctx: commands.Context, container_name: str):
        """Remove a custom container mapping."""
        async with self.config.guild(ctx.guild).custom_games() as custom:
            if container_name.lower() not in custom:
                await ctx.send(f"`{container_name}` is not in custom mappings.", ephemeral=True)
                return
            del custom[container_name.lower()]
        await ctx.send(f"Removed custom mapping for `{container_name}`.", ephemeral=True)

    @gsm.command(name="list")
    async def gsm_list(self, ctx: commands.Context):
        """Show the current configuration for this server."""
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data["channel_id"]) if data["channel_id"] else None
        admin_ch = ctx.guild.get_channel(data["admin_channel_id"]) if data.get("admin_channel_id") else None
        tracked = data.get("tracked_rows", {})
        custom = data.get("custom_games", {})
        monitored = data.get("monitored")

        lines = [
            f"**GSM Channel:** {channel.mention if channel else 'Not set'}",
            f"**Admin Channel:** {admin_ch.mention if admin_ch else 'Not set (defaults to GSM channel)'}",
            f"**Connect Host:** `{data.get('connect_host') or 'Not set (uses bridge IP)'}`",
            f"**DB Path:** `{data['db_path']}`",
            f"**Tracked:** {', '.join(f'`{k}`' for k in tracked) or 'none'}",
            f"**Custom mappings:** {', '.join(f'`{k}`' for k in custom) or 'none'}",
            f"**Monitored:** {'all recognized' if monitored is None else ', '.join(f'`{m}`' for m in monitored)}",
            f"**Games cache:** {len(self._games_cache)} games loaded",
        ]
        await ctx.send("\n".join(lines), ephemeral=True)

    @gsm.command(name="status")
    async def gsm_status(self, ctx: commands.Context):
        """Health check: Docker socket, DB, and event listener."""
        data = await self.config.guild(ctx.guild).all()
        db_path = data["db_path"]
        docker_ok = DockerListener.docker_available()
        db_ok = is_db_writable(db_path)
        listener_ok = self._listener is not None and self._listener.is_connected

        lines = [
            f"{'✅' if docker_ok else '❌'} Docker socket: {'reachable' if docker_ok else 'NOT reachable — ensure /var/run/docker.sock is mounted and run chmod 666 /var/run/docker.sock'}",
            f"{'✅' if db_ok else '❌'} DB at `{db_path}`: {'writable' if db_ok else 'NOT writable — check path and container mount'}",
            f"{'✅' if listener_ok else '❌'} Event listener: {'running' if listener_ok else 'not running'}",
            f"{'✅' if self._games_cache else '⚠️'} Games cache: {len(self._games_cache)} games loaded",
        ]
        await ctx.send("\n".join(lines), ephemeral=True)

    @gsm.command(name="reloadgames")
    async def gsm_reloadgames(self, ctx: commands.Context):
        """Reload the DiscordGSM games list from the container."""
        self._games_cache = load_games_csv()
        await ctx.send(f"Reloaded games cache: {len(self._games_cache)} games.", ephemeral=True)

    @gsm.command(name="scan")
    async def gsm_scan(self, ctx: commands.Context):
        """Interactively select which running containers to monitor."""
        if not DockerListener.docker_available():
            await ctx.send("❌ Docker socket not reachable. Check your container setup.", ephemeral=True)
            return

        running = DockerListener.list_running_containers()
        if not running:
            await ctx.send("No running containers found.", ephemeral=True)
            return

        guild_data = await self.config.guild(ctx.guild).all()

        containers = []
        for name in running:
            info = self._resolve_game_info(name, guild_data)
            containers.append({"name": name, "known": info is not None, "info": info})

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
                name="❓ Unknown (will be ignored unless you add them manually)",
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
                    f"(Reply within 30s, or type `skip`)"
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

        if custom_additions:
            async with self.config.guild(ctx.guild).custom_games() as custom:
                custom.update(custom_additions)

        await self.config.guild(ctx.guild).monitored.set(list(selected))

        db_path = guild_data["db_path"]
        channel_id = guild_data["channel_id"]
        if not channel_id:
            await ctx.send(
                "⚠️ No channel set. Run `/gsm channel #your-channel` first, then scan again."
            )
            return

        fresh_guild_data = await self.config.guild(ctx.guild).all()
        tracked = fresh_guild_data.get("tracked_rows", {})

        # Remove rows for deselected containers
        for name, row_id in list(tracked.items()):
            if name not in selected:
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

        # Insert rows for newly selected containers
        for name in selected:
            if name in tracked:
                continue
            info = self._resolve_game_info(name, fresh_guild_data)
            if info:
                await self._insert_for_guild(ctx.guild, name, info, db_path, fresh_guild_data)

        count = len(selected)
        await ctx.send(f"✅ Monitoring {count} container{'s' if count != 1 else ''}.", ephemeral=True)
