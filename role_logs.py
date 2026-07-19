"""
Ког логирования всего, что связано с ролями на сервере:

1. Кому какая роль выдана/снята (on_member_update) — с попыткой определить,
   кто именно это сделал, через audit log сервера.
2. Создание новой роли на сервере (on_guild_role_create).
3. Удаление роли с сервера (on_guild_role_delete).
4. Изменение самой роли — цвет, название, права, hoist/mentionable
   (on_guild_role_update) — тоже с попыткой определить, кто это сделал.

Все события пишутся в settings.ROLE_LOG_CHANNEL_ID, с максимально подробной
информацией: кто, кому, когда, какая именно роль (цвет, позиция, права),
причина (если указана при выдаче/снятии через Discord API) и т.д.

ВАЖНО: чтобы бот мог определить, КТО выдал/снял/создал/удалил/изменил роль,
ему нужно право "View Audit Log" (Просмотр журнала аудита). Без этого права
лог всё равно отправится (сам факт изменения виден по on_member_update /
on_guild_role_*), но поле "Кто изменил" будет содержать "не удалось определить".
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

# Права, которые имеет смысл подсвечивать в логе как "ключевые" — полный список
# прав слишком длинный и бесполезен для быстрого чтения лога.
NOTABLE_PERMISSIONS = (
    ("administrator", "Администратор"),
    ("manage_guild", "Управление сервером"),
    ("manage_roles", "Управление ролями"),
    ("manage_channels", "Управление каналами"),
    ("manage_messages", "Управление сообщениями"),
    ("manage_webhooks", "Управление вебхуками"),
    ("manage_nicknames", "Управление никнеймами"),
    ("manage_events", "Управление событиями"),
    ("kick_members", "Кик участников"),
    ("ban_members", "Бан участников"),
    ("moderate_members", "Модерация участников (тайм-аут)"),
    ("mention_everyone", "Упоминание @everyone"),
    ("mute_members", "Мьют в голосовых каналах"),
    ("deafen_members", "Заглушение в голосовых каналах"),
    ("move_members", "Перемещение участников"),
)


def _notable_perms_text(permissions: discord.Permissions) -> str:
    active = [label for attr, label in NOTABLE_PERMISSIONS if getattr(permissions, attr, False)]
    if not active:
        return "нет ключевых прав"
    return ", ".join(active)


def _role_details_text(role: discord.Role) -> str:
    color_hex = f"#{role.color.value:06x}" if role.color.value else "нет (по умолчанию)"
    return (
        f"Цвет: **{color_hex}**\n"
        f"Позиция: **{role.position}**\n"
        f"Показывается отдельно от онлайн-участников: **{'да' if role.hoist else 'нет'}**\n"
        f"Можно упомянуть всем: **{'да' if role.mentionable else 'нет'}**\n"
        f"Ключевые права: {_notable_perms_text(role.permissions)}"
    )


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
        return f"{actor.mention} (`{actor.id}`) — {actor}"

    async def _send(self, guild: discord.Guild, embed: discord.Embed):
        channel = await self._log_channel(guild)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Не удалось отправить лог ролей в канал %s", channel.id)

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
        if await self._log_channel(guild) is None:
            return

        actor, reason = await self._find_actor(guild, discord.AuditLogAction.member_role_update, after.id)

        embed = discord.Embed(
            title="Изменение ролей участника",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.add_field(name="Участник", value=f"{after.mention} (`{after.id}`)", inline=False)
        embed.add_field(
            name="Аккаунт создан",
            value=f"<t:{int(after.created_at.timestamp())}:F> (<t:{int(after.created_at.timestamp())}:R>)",
            inline=True,
        )
        if after.joined_at:
            embed.add_field(
                name="На сервере с",
                value=f"<t:{int(after.joined_at.timestamp())}:F> (<t:{int(after.joined_at.timestamp())}:R>)",
                inline=True,
            )
        if added:
            embed.add_field(
                name=f"Роли выданы ✅ ({len(added)})",
                value="\n".join(f"{r.mention} (`{r.id}`) — позиция {r.position}" for r in added),
                inline=False,
            )
        if removed:
            embed.add_field(
                name=f"Роли сняты ❌ ({len(removed)})",
                value="\n".join(f"{r.mention} (`{r.id}`) — позиция {r.position}" for r in removed),
                inline=False,
            )
        embed.add_field(name="Кто изменил", value=self._actor_field_value(actor), inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason[:1024], inline=False)
        embed.add_field(
            name="Всего ролей у участника сейчас",
            value=str(len(after_roles) - 1 if guild.default_role in after_roles else len(after_roles)),
            inline=True,
        )
        embed.set_footer(text=f"ID участника: {after.id}")

        await self._send(guild, embed)

    # ---------- создание новой роли на сервере ----------
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if await self._log_channel(role.guild) is None:
            return

        actor, reason = await self._find_actor(role.guild, discord.AuditLogAction.role_create, role.id)

        embed = discord.Embed(
            title="Создана новая роль",
            color=role.color if role.color.value else EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Роль", value=f"{role.mention} (`{role.id}`)\n**{role.name}**", inline=False)
        embed.add_field(name="Подробности роли", value=_role_details_text(role), inline=False)
        embed.add_field(name="Кто создал", value=self._actor_field_value(actor), inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason[:1024], inline=False)
        if role.icon:
            embed.set_thumbnail(url=role.icon.url)
        embed.set_footer(text=f"ID роли: {role.id} | Всего ролей на сервере: {len(role.guild.roles)}")

        await self._send(role.guild, embed)

    # ---------- удаление роли с сервера ----------
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if await self._log_channel(role.guild) is None:
            return

        actor, reason = await self._find_actor(role.guild, discord.AuditLogAction.role_delete, role.id)

        embed = discord.Embed(
            title="Роль удалена",
            color=role.color if role.color.value else EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Роль", value=f"**{role.name}** (`{role.id}`)", inline=False)
        embed.add_field(name="Подробности удалённой роли", value=_role_details_text(role), inline=False)
        embed.add_field(
            name="Участников с этой ролью на момент удаления",
            value=str(len(role.members)),
            inline=True,
        )
        embed.add_field(name="Кто удалил", value=self._actor_field_value(actor), inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason[:1024], inline=False)
        embed.set_footer(text=f"ID роли: {role.id}")

        await self._send(role.guild, embed)

    # ---------- изменение самой роли (цвет, название, права, hoist и т.д.) ----------
    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes: list[tuple[str, str, str]] = []  # (поле, было, стало)

        if before.name != after.name:
            changes.append(("Название", before.name, after.name))
        if before.color != after.color:
            before_hex = f"#{before.color.value:06x}" if before.color.value else "нет"
            after_hex = f"#{after.color.value:06x}" if after.color.value else "нет"
            changes.append(("Цвет", before_hex, after_hex))
        if before.hoist != after.hoist:
            changes.append(("Показ отдельно от участников", "да" if before.hoist else "нет", "да" if after.hoist else "нет"))
        if before.mentionable != after.mentionable:
            changes.append(("Можно упомянуть всем", "да" if before.mentionable else "нет", "да" if after.mentionable else "нет"))
        if before.permissions != after.permissions:
            changes.append(("Ключевые права", _notable_perms_text(before.permissions), _notable_perms_text(after.permissions)))
        if before.position != after.position:
            changes.append(("Позиция", str(before.position), str(after.position)))

        if not changes:
            return

        guild = after.guild
        if await self._log_channel(guild) is None:
            return

        actor, reason = await self._find_actor(guild, discord.AuditLogAction.role_update, after.id)

        embed = discord.Embed(
            title="Роль изменена",
            color=after.color if after.color.value else EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Роль", value=f"{after.mention} (`{after.id}`)", inline=False)
        for field_name, old_value, new_value in changes:
            embed.add_field(name=field_name, value=f"было: **{old_value}**\nстало: **{new_value}**", inline=True)
        embed.add_field(name="Кто изменил", value=self._actor_field_value(actor), inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason[:1024], inline=False)
        embed.set_footer(text=f"ID роли: {after.id}")

        await self._send(guild, embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleLogs(bot))
