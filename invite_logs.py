"""
Ког логов приглашений.

При заходе нового участника бот определяет, по какой инвайт-ссылке
он пришёл (сравнивая счётчики использований до/после), и пишет об этом
в лог-канал: кто зашёл, чей это инвайт, код и текущее число использований.

Требуется право бота "Manage Server" (Manage Guild) — без него Discord
не даёт получить список инвайтов сервера.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

import settings

log = logging.getLogger("wildsync.invites")


class InviteLogs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> {invite_code: uses}
        self.invite_cache: dict[int, dict[str, int]] = {}

    async def _cache_guild_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            log.warning(
                "Нет прав на просмотр инвайтов сервера %s (нужно право Manage Server)",
                guild.id,
            )
            self.invite_cache[guild.id] = {}
            return
        except discord.HTTPException:
            log.exception("Не удалось получить список инвайтов сервера %s", guild.id)
            return

        self.invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild is None:
            return
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild is None:
            return
        self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        before = self.invite_cache.get(guild.id, {})

        try:
            current_invites = await guild.invites()
        except discord.Forbidden:
            log.warning("Нет прав на просмотр инвайтов сервера %s", guild.id)
            return
        except discord.HTTPException:
            log.exception("Не удалось получить список инвайтов сервера %s", guild.id)
            return

        after = {invite.code: invite.uses or 0 for invite in current_invites}
        used_invite = None

        for invite in current_invites:
            if invite.uses and invite.uses > before.get(invite.code, 0):
                used_invite = invite
                break

        # обновляем кэш на актуальный
        self.invite_cache[guild.id] = after

        await self._send_log(member, used_invite)

    async def _send_log(self, member: discord.Member, invite: discord.Invite | None):
        if not settings.INVITE_LOG_CHANNEL_ID:
            return

        channel = member.guild.get_channel(settings.INVITE_LOG_CHANNEL_ID)
        if channel is None:
            log.warning("Канал логов приглашений %s не найден", settings.INVITE_LOG_CHANNEL_ID)
            return

        embed = discord.Embed(color=discord.Color(0x808080))
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)

        if invite is not None:
            inviter = invite.inviter
            embed.description = (
                f"📥 {member.mention} зашёл по инвайту от "
                f"{inviter.mention if inviter else 'неизвестно'}"
            )
            embed.add_field(name="Код инвайта", value=f"`{invite.code}`", inline=True)
            embed.add_field(name="Использований", value=str(invite.uses or 0), inline=True)
        else:
            embed.description = (
                f"📥 {member.mention} зашёл на сервер "
                f"(не удалось определить инвайт — возможно, vanity-ссылка или виджет)"
            )

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Не удалось отправить лог приглашения в канал %s", channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(InviteLogs(bot))
