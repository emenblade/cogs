from redbot.core.bot import Red
from .button import Button321

__red_end_user_data_statement__ = (
    "This cog stores the timestamp of when a user pressed the button "
    "and whether they have been sent the self-destruct DM. "
    "Data can be deleted on request via `[p]mydata forgetme`."
)


async def setup(bot: Red) -> None:
    cog = Button321(bot)
    await bot.add_cog(cog)
    await cog.initialize()
