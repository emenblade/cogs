from redbot.core.bot import Red
from .filecab import Filecab

__red_end_user_data_statement__ = (
    "This cog stores document filing answers and per-user filing state linked "
    "to Discord user IDs. Data can be deleted on request via `[p]mydata forgetme`."
)


async def setup(bot: Red) -> None:
    cog = Filecab(bot)
    await bot.add_cog(cog)
    await cog.initialize()
