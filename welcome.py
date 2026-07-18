"""
Ког, отвечающий за приветствие новых участников.

При заходе нового пользователя на сервер бот генерирует картинку
(аватар, ник, номер участника, название сервера) и отправляет её
в канал приветствия.
"""

import logging

import discord
from discord.ext import commands

from config import settings
from utils.image_generator import generate_welcome_card

log = logging.getLogger("wildsync.welcome")


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        channel = member.guild.get_channel(settings.WELCOME_CHANNEL_ID)
        if channel is None:
            log.warning("Канал приветствия %s не найден", settings.WELCOME_CHANNEL_ID)
            return

        try:
            avatar_bytes = await member.display_avatar.replace(size=256).read()
        except discord.HTTPException:
            log.exception("Не удалось загрузить аватар для %s", member)
            return

        try:
            card = await generate_welcome_card(
                avatar_bytes=avatar_bytes,
                username=member.display_name,
                member_number=member.guild.member_count,
                server_name=member.guild.name,
            )
        except Exception:
            log.exception("Ошибка генерации карточки приветствия")
            return

        file = discord.File(card, filename="welcome.png")

        try:
            await channel.send(
                content=f"{member.mention} добро пожаловать на **{member.guild.name}**! 🎉",
                file=file,
            )
        except discord.HTTPException:
            log.exception("Не удалось отправить приветствие в канал %s", channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
