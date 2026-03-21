from redbot.core.bot import Red
from .forms import Forms

__red_end_user_data_statement__ = (
    "This cog stores application answers, ticket transcripts, and per-user "
    "state linked to Discord user IDs. Data can be deleted on request via "
    "`[p]mydata forgetme`."
)


async def setup(bot: Red) -> None:
    cog = Forms(bot)
    await bot.add_cog(cog)
    await cog.initialize()
