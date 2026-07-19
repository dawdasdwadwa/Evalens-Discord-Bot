"""
Ког, отвечающий за приветствие новых участников.
"""

import logging

import discord
from discord.ext import commands

import settings
from image_generator import generate_welcome_card

log = logging.getLogger("wildsync.welcome")


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        # --- выдача роли при входе ---
        if settings.JOIN_ROLE_ID:
            role = member.guild.get_role(settings.JOIN_ROLE_ID)
            if role is None:
                log.warning("Роль с ID %s не найдена на сервере", settings.JOIN_ROLE_ID)
            else:
                try:
                    await member.add_roles(role, reason="Автоматическая роль при входе")
                except discord.Forbidden:
                    log.error("Недостаточно прав, чтобы выдать роль %s участнику %s", role, member)
                except discord.HTTPException:
                    log.exception("Не удалось выдать роль %s участнику %s", role, member)

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
                content=f"{member.mention}",
                file=file,
            )
        except discord.HTTPException:
            log.exception("Не удалось отправить приветствие в канал %s", channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
