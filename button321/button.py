from __future__ import annotations
import asyncio
import time
import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


class SelfDestructView(discord.ui.View):
    def __init__(self, config: Config, bot: Red) -> None:
        super().__init__(timeout=None)
        self.config = config
        self.bot = bot

    @discord.ui.button(
        label="self destruct do not press",
        style=discord.ButtonStyle.danger,
        custom_id="321button:self_destruct",
    )
    async def press_me(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await interaction.response.send_message(
            "You weren't supposed to press the button.", ephemeral=True
        )

        guild_id = interaction.guild_id

        log_channel_id = await self.config.guild_from_id(guild_id).log_channel()
        if log_channel_id:
            channel = interaction.guild.get_channel(log_channel_id)
            if channel:
                await channel.send(
                    f"🚨 {interaction.user.mention} pressed the button at "
                    f"<t:{int(time.time())}:F>"
                )

        async with self.config.guild_from_id(guild_id).pending_dms() as dms:
            dms[str(interaction.user.id)] = int(time.time())


class ChannelSelectView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        self.selected: discord.abc.GuildChannel | None = None
        self.cancelled: bool = False

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select a channel…",
        channel_types=[discord.ChannelType.text],
    )
    async def channel_select(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ) -> None:
        self.selected = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if self.selected is None:
            await interaction.response.send_message(
                "⚠️ Select a channel first.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content=f"✅ Selected {self.selected.mention}.", view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        self.cancelled = True
        await interaction.response.edit_message(
            content="❌ Setup cancelled.", view=None, embed=None
        )
        self.stop()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


class Button321(commands.Cog):
    """A self-destruct button that DMs you 6 hours after pressing it."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=0x33323162, force_registration=True
        )
        self._bg_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        self.config.register_guild(
            button_channel=None,
            log_channel=None,
            button_message_id=None,
            pending_dms={},
        )
        self.config.register_user(
            pressed_at=None,
            notified=False,
        )
        await self._register_persistent_views()
        self._bg_task = asyncio.create_task(self._dm_loop())

    async def _register_persistent_views(self) -> None:
        all_guilds = await self.config.all_guilds()
        for guild_id_str, data in all_guilds.items():
            msg_id = data.get("button_message_id")
            if msg_id:
                self.bot.add_view(
                    SelfDestructView(self.config, self.bot),
                    message_id=msg_id,
                )

    async def _dm_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                await self._process_pending_dms()
            except Exception:
                pass
            await asyncio.sleep(60)

    async def _process_pending_dms(self) -> None:
        all_guilds = await self.config.all_guilds()
        now = int(time.time())
        six_hours = 6 * 3600
        for guild_id_str, data in all_guilds.items():
            pending = data.get("pending_dms", {})
            if not pending:
                continue
            to_del: list[str] = []
            guild = self.bot.get_guild(int(guild_id_str))
            if guild is None:
                continue
            for user_id_str, press_time in pending.items():
                if now - press_time >= six_hours:
                    user = self.bot.get_user(int(user_id_str))
                    if user:
                        try:
                            await user.send(
                                "💥 **The self-destruct sequence has been initiated.**\n\n"
                                "You really shouldn't have pressed that button."
                            )
                            await self.config.user(user).notified.set(True)
                        except discord.Forbidden:
                            pass
                    to_del.append(user_id_str)
            if to_del:
                async with self.config.guild_from_id(
                    int(guild_id_str)
                ).pending_dms() as dms:
                    for uid in to_del:
                        dms.pop(uid, None)

    @commands.is_owner()
    @commands.hybrid_group(name="321button")
    async def button_group(self, ctx: commands.Context) -> None:
        """Manage the 321button cog."""

    @button_group.command(name="setup")
    @commands.is_owner()
    async def setup(self, ctx: commands.Context) -> None:
        """Set up the self-destruct button (owner only)."""
        channel_view = ChannelSelectView()
        embed1 = discord.Embed(
            title="321Button Setup — Step 1 of 2",
            description="Select the **channel** where the self-destruct button should be posted.",
            color=discord.Color.red(),
        )
        await ctx.send(embed=embed1, view=channel_view)
        await channel_view.wait()
        if channel_view.cancelled or channel_view.selected is None:
            return

        channel_id = channel_view.selected.id

        log_view = ChannelSelectView()
        embed2 = discord.Embed(
            title="321Button Setup — Step 2 of 2",
            description="Select the **log channel** where button press activities will be reported.",
            color=discord.Color.red(),
        )
        await ctx.send(embed=embed2, view=log_view)
        await log_view.wait()
        if log_view.cancelled or log_view.selected is None:
            return

        log_channel_id = log_view.selected.id

        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            await ctx.send("❌ Configured channel no longer exists.", ephemeral=True)
            return

        view = SelfDestructView(self.config, self.bot)
        msg = await channel.send(
            embed=discord.Embed(
                title="🚨 DO NOT PRESS 🚨",
                description="There is a button below. You probably shouldn't press it.",
                color=discord.Color.red(),
            ),
            view=view,
        )

        await self.config.guild(ctx.guild).button_channel.set(channel_id)
        await self.config.guild(ctx.guild).log_channel.set(log_channel_id)
        await self.config.guild(ctx.guild).button_message_id.set(msg.id)
        self.bot.add_view(view, message_id=msg.id)

        await ctx.send(
            f"✅ Button posted in {channel.mention}! Logs will go to <#{log_channel_id}>.",
            ephemeral=True,
        )

    @button_group.command(name="repost")
    @commands.is_owner()
    async def repost(self, ctx: commands.Context) -> None:
        """Re-post the self-destruct button (owner only)."""
        guild_data = await self.config.guild(ctx.guild).all()
        channel_id = guild_data.get("button_channel")
        log_channel_id = guild_data.get("log_channel")

        if not channel_id:
            await ctx.send(
                "⚠️ Run `321button setup` first.", ephemeral=True
            )
            return

        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            await ctx.send(
                "❌ Configured channel no longer exists.", ephemeral=True
            )
            return

        view = SelfDestructView(self.config, self.bot)
        msg = await channel.send(
            embed=discord.Embed(
                title="🚨 DO NOT PRESS 🚨",
                description="There is a button below. You probably shouldn't press it.",
                color=discord.Color.red(),
            ),
            view=view,
        )

        await self.config.guild(ctx.guild).button_message_id.set(msg.id)
        self.bot.add_view(view, message_id=msg.id)

        await ctx.send(
            f"✅ Button re-posted in {channel.mention}.", ephemeral=True
        )

    @button_group.command(name="status")
    @commands.is_owner()
    async def status(self, ctx: commands.Context) -> None:
        """Show button and pending notification status (owner only)."""
        guild_data = await self.config.guild(ctx.guild).all()
        pending = guild_data.get("pending_dms", {})
        embed = discord.Embed(
            title="321Button Status",
            color=discord.Color.blurple(),
        )
        channel_id = guild_data.get("button_channel")
        log_channel_id = guild_data.get("log_channel")
        embed.add_field(
            name="Button Channel",
            value=f"<#{channel_id}>" if channel_id else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Log Channel",
            value=f"<#{log_channel_id}>" if log_channel_id else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Pending DMs",
            value=str(len(pending)),
            inline=True,
        )
        if pending:
            now = int(time.time())
            lines = []
            for uid, ts in list(pending.items())[:10]:
                remaining = 6 * 3600 - (now - ts)
                if remaining > 0:
                    lines.append(
                        f"<@{uid}> — DM in {remaining // 3600}h{remaining % 3600 // 60}m"
                    )
                else:
                    lines.append(f"<@{uid}> — due now")
            if lines:
                embed.add_field(
                    name="Upcoming Notifications",
                    value="\n".join(lines),
                    inline=False,
                )
        await ctx.send(embed=embed, ephemeral=True)

    async def red_get_data_for_user(
        self, *, requester: str, user_id: int
    ) -> dict:
        user = self.bot.get_user(user_id) or discord.Object(id=user_id)
        data = await self.config.user(user).all()
        return {"user_data": data} if any(v is not None for v in data.values()) else {}

    async def red_delete_data_for_user(
        self, *, requester: str, user_id: int
    ) -> None:
        user = self.bot.get_user(user_id) or discord.Object(id=user_id)
        await self.config.user(user).clear()
        for guild in self.bot.guilds:
            async with self.config.guild(guild).pending_dms() as dms:
                dms.pop(str(user_id), None)

    def cog_unload(self) -> None:
        if self._bg_task:
            self._bg_task.cancel()
