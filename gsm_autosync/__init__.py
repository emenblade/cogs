from .gsm_autosync import GsmAutoSync

async def setup(bot):
    await bot.add_cog(GsmAutoSync(bot))
