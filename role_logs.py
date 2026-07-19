"""
Ког логирования всего, что связано с ролями на сервере:

1. Кому какая роль выдана/снята (on_member_update) — с попыткой определить,
   кто именно это сделал, через audit log сервера.
2. Создание новой роли на сервере (on_guild_role_create).
3. Удаление роли с сервера (on_guild_role_delete).

Все события пишутся в settings.ROLE_LOG_CHANNEL_ID.

ВАЖНО: чтобы бот мог определить, КТО выдал/снял/создал/удалил роль, ему нужно
право "View Audit Log" (Просмотр журнала аудита). Без этого права лог всё равно
отправится (сам факт изменения ролей виден по on_member_update / on_guild_role_*),
но поле "Кто изменил" будет содержать "не удалось определить".
"""

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import settings

log = logging.getLogger("evalens.role_logs")

EMBED_COLOR = discord.Color(0x808080)

# Сколько секунд назад должна была произойти запись в audit log, чтобы мы
# посчитали её "той самой" причиной события, которое сейчас логируем.
AUDIT_LOG_MATCH_WINDOW = 15


class RoleLogs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _log_channel(self, guild: discord.Guild):
        if not settings.ROLE_LOG_CHANNEL_ID:
            return None
        channel = guild.get_channel(settings.ROLE_LOG_CHANNEL_ID)
        if channel is None:
            log.warning("Канал логов ролей %s не найден на сервере %s", settings.ROLE_LOG_CHANNEL_ID, guild.id)
        return channel

    async def _find_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int):
        """Ищет в audit log недавнюю запись нужного действия с указанной целью.
        Возвращает (пользователь, причина) или (None, None), если не нашли
        (например, нет права View Audit Log, или изменение сделано напрямую
        через Discord API/бота без соответствующей записи)."""
        try:
            async for entry in guild.audit_logs(limit=15, action=action):
                age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
                if age > AUDIT_LOG_MATCH_WINDOW:
                    break
                target = entry.target
                if target is None or getattr(target, "id", None) != target_id:
                    continue
                return entry.user, entry.reason
        except discord.Forbidden:
            log.warning(
                "Нет права View Audit Log на сервере %s — не могу определить, кто изменил роли", guild.id
            )
        except discord.HTTPException:
            log.exception("Ошибка чтения audit log сервера %s", guild.id)
        return None, None

    @staticmethod
    def _actor_field_value(actor: discord.abc.User | None) -> str:
        if actor is None:
            return "не удалось определить (нет права View Audit Log или изменено напрямую через API)"
        return f"{actor.mention} (`{actor.id}`)"

    # ---------- выдача/снятие ролей участнику ----------
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return

        before_roles = set(before.roles)
        after_roles = set(after.roles)
        added = sorted((r for r in after_roles - before_roles if not r.is_default()), key=lambda r: r.position, reverse=True)
        removed = sorted((r for r in before_roles - after_roles if not r.is_default()), key=lambda r: r.position, reverse=True)
        if not added and not removed:
            return

        guild = after.guild
        channel = await self._log_channel(guild)
        if channel is None:
            return

        actor, reason = await self._find_actor(guild, discord.AuditLogAction.member_role_update, after.id)

        embed = discord.Embed(
            title="Изменение ролей участника",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        embed.add_field(name="Участник", value=f"{after.mention} (`{after.id}`)", inline=False)
        if added:
            embed.add_field(
                name="Роли выданы ✅",
                value="\n".join(f"{r.mention} (`{r.id}`)" for r in added),
                inline=False,
            )
        if removed:
            embed.add_field(
                name="Роли сняты ❌",
                value="\n".join(f"{r.mention} (`{r.id}`)" for r in removed),
                inline=False,
            )
        embed.add_field(name="Кто изменил", value=self._actor_field_value(actor), inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason[:1024], inline=False)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Не удалось отправить лог изменения ролей в канал %s", channel.id)

    # ---------- создание новой роли на сервере ----------
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        channel = await self._log_channel(role.guild)
        if channel is None:
            return

        actor, reason = await self._find_actor(role.guild, discord.AuditLogAction.role_create, role.id)

        embed = discord.Embed(
            title="Создана новая роль",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Роль", value=f"{role.mention} (`{role.id}`)", inline=False)
        embed.add_field(name="Кто создал", value=self._actor_field_value(actor), inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason[:1024], inline=False)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Не удалось отправить лог создания роли в канал %s", channel.id)

    # ---------- удаление роли с сервера ----------
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        channel = await self._log_channel(role.guild)
        if channel is None:
            return

        actor, reason = await self._find_actor(role.guild, discord.AuditLogAction.role_delete, role.id)

        embed = discord.Embed(
            title="Роль удалена",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Роль", value=f"**{role.name}** (`{role.id}`)", inline=False)
        embed.add_field(name="Кто удалил", value=self._actor_field_value(actor), inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason[:1024], inline=False)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Не удалось отправить лог удаления роли в канал %s", channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleLogs(bot))
