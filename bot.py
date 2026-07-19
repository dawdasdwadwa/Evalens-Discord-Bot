"""
Точка входа бота Wildsync.
"""

import asyncio
import logging

import discord
from discord.ext import commands

import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("wildsync.bot")

INTENTS = discord.Intents.default()
INTENTS.members = True  # обязательно для on_member_join

INITIAL_COGS = (
    "welcome",
    "verification",
    "invite_logs",
)


class WildsyncBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        for cog in INITIAL_COGS:
            try:
                await self.load_extension(cog)
                log.info("Загружен ког: %s", cog)
            except Exception:
                log.exception("Не удалось загрузить ког %s", cog)

        synced = await self.tree.sync()
        log.info("Синхронизировано %d slash-команд", len(synced))

    async def on_ready(self):
        log.info("Бот запущен как %s (ID: %s)", self.user, self.user.id)


async def main():
    if not settings.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN не задан. Проверьте переменные окружения")

    bot = WildsyncBot()
    async with bot:
        await bot.start(settings.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
