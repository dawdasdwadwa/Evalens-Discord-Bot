"""
Ког, определяющий, по какому инвайту зашёл участник, и логирующий это.

Требует право бота "Manage Server" (Manage Guild), иначе guild.invites()
вернёт пустой список / вызовет Forbidden.

Логика:
1. При старте бота (on_ready) кешируем текущее состояние всех инвайтов
   каждого сервера: {invite.code: invite.uses}.
2. Дополнительно слушаем on_invite_create / on_invite_delete, чтобы кеш
   не устаревал между заходами участников.
3. При on_member_join сравниваем свежий список инвайтов с закешированным.
   Тот инвайт, у которого uses стало больше, чем было — это и есть
   ссылка, по которой зашёл участник.
4. Если ни один счётчик не вырос (vanity-ссылка или виджет сервера —
   Discord API не отдаёт для них статистику использований), честно
   пишем "не удалось определить".
"""

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import settings

log = logging.getLogger("evalens.invite_logs")


class InviteLogs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild.id -> {invite_code: uses}
        self.invite_cache: dict[int, dict[str, int]] = {}

    async def cache_guild_invites(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            log.warning(
                "Нет права Manage Server на сервере %s (%s) — не могу прочитать инвайты",
                guild.name, guild.id,
            )
            self.invite_cache[guild.id] = {}
            return
        except discord.HTTPException as e:
            log.warning("Не удалось получить инвайты сервера %s: %s", guild.id, e)
            return

        self.invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)
        log.info("invite_logs: кеш инвайтов заполнен для %d серверов", len(self.bot.guilds))

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        cache = self.invite_cache.get(invite.guild.id)
        if cache is not None:
            cache.pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        log_channel = guild.get_channel(settings.INVITE_LOG_CHANNEL_ID)
        if log_channel is None:
            log.warning("Канал логов инвайтов %s не найден", settings.INVITE_LOG_CHANNEL_ID)
            return

        old_cache = self.invite_cache.get(guild.id, {})

        try:
            current_invites = await guild.invites()
        except discord.Forbidden:
            await self._send_unknown(log_channel, member, reason=(
                "у бота нет права **Manage Server** — список инвайтов недоступен"
            ))
            return
        except discord.HTTPException as e:
            await self._send_unknown(log_channel, member, reason=f"ошибка Discord API: {e}")
            return

        used_invite = None
        for invite in current_invites:
            old_uses = old_cache.get(invite.code, 0)
            new_uses = invite.uses or 0
            if new_uses > old_uses:
                used_invite = invite
                break

        self.invite_cache[guild.id] = {inv.code: inv.uses or 0 for inv in current_invites}

        if used_invite is None:
            await self._send_unknown(log_channel, member, reason=(
                "это vanity-ссылка сервера или виджет — Discord API не отдаёт "
                "для них статистику использований"
            ))
            return

        await self._send_known(log_channel, member, used_invite)

    async def _send_known(self, channel: discord.TextChannel, member: discord.Member, invite: discord.Invite):
        joined_at = member.joined_at or datetime.now(timezone.utc)
        joined_ts = int(joined_at.timestamp())

        inviter = invite.inviter
        inviter_text = f"{inviter.mention} (`{inviter.id}`)" if inviter else "неизвестно (бот/удалён)"

        if invite.created_at:
            created_ts = int(invite.created_at.timestamp())
            created_text = f"<t:{created_ts}:F> (<t:{created_ts}:R>)"
        else:
            created_text = "неизвестно"

        embed = discord.Embed(
            title="Новый участник по приглашению",
            color=discord.Color(0x808080),
            timestamp=joined_at,
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Зашёл", value=f"<t:{joined_ts}:F> (<t:{joined_ts}:R>)", inline=False)
        embed.add_field(
            name="Приглашение",
            value=f"`discord.gg/{invite.code}` — использований: {invite.uses}",
            inline=False,
        )
        embed.add_field(name="Кем создано", value=inviter_text, inline=True)
        embed.add_field(name="Когда создано", value=created_text, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)

        await channel.send(embed=embed)

    async def _send_unknown(self, channel: discord.TextChannel, member: discord.Member, reason: str):
        joined_at = member.joined_at or datetime.now(timezone.utc)
        joined_ts = int(joined_at.timestamp())

        embed = discord.Embed(
            title="Новый участник — приглашение не определено",
            description=f"Не удалось определить, по какой ссылке зашли: {reason}",
            color=discord.Color(0x808080),
            timestamp=joined_at,
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Зашёл", value=f"<t:{joined_ts}:F> (<t:{joined_ts}:R>)", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)

        await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(InviteLogs(bot))
