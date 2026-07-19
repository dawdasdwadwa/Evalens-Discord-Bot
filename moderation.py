import json
import logging
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import settings

log = logging.getLogger("evalens.moderation")

TEMP_BANS_FILE = "temp_bans.json"

DURATION_RE = re.compile(r"^(\d+)\s*([smhdwSMHDW])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
PERMANENT_WORDS = {"навсегда", "forever", "perm", "permanent", "0"}


def parse_duration(raw: str) -> Optional[timedelta]:
    """Парсит строку вида '10m', '2h', '3d', '1w'. Возвращает None, если 'навсегда'."""
    raw = raw.strip().lower()
    if raw in PERMANENT_WORDS:
        return None
    match = DURATION_RE.match(raw)
    if not match:
        raise ValueError(
            "Неверный формат срока. Примеры: 10m, 2h, 3d, 1w. Для бана можно также 'навсегда'."
        )
    amount, unit = match.groups()
    seconds = int(amount) * UNIT_SECONDS[unit.lower()]
    if seconds <= 0:
        raise ValueError("Срок должен быть больше нуля.")
    return timedelta(seconds=seconds)


def format_duration(delta: Optional[timedelta]) -> str:
    if delta is None:
        return "Навсегда"
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} дн.")
    if hours:
        parts.append(f"{hours} ч.")
    if minutes:
        parts.append(f"{minutes} мин.")
    if seconds and not parts:
        parts.append(f"{seconds} сек.")
    return " ".join(parts) if parts else "меньше минуты"


EMBED_COLOR = discord.Color.light_grey()

# ---------- пороги антиспама ----------
SPAM_MENTION_LIMIT = 5      # упоминаний (пользователи+роли) в одном сообщении -> спам пингами
SPAM_FLOOD_COUNT = 5        # сообщений подряд...
SPAM_FLOOD_WINDOW = 3       # ...за столько секунд -> спам сообщениями
SPAM_DUPLICATE_COUNT = 3    # одинаковых сообщений...
SPAM_DUPLICATE_WINDOW = 20  # ...за столько секунд -> спам одинаковыми сообщениями

# Если в settings.py ещё не добавлена переменная PROFILE_ROLE_IDS —
# используем роли стаффа, чтобы ког не падал при загрузке.
PROFILE_ROLE_IDS = getattr(settings, "PROFILE_ROLE_IDS", settings.STAFF_ROLE_IDS)
if not hasattr(settings, "PROFILE_ROLE_IDS"):
    log.warning(
        "В settings.py нет PROFILE_ROLE_IDS — /profile временно доступна только стаффу. "
        "Добавь PROFILE_ROLE_IDS, чтобы открыть команду нужной роли."
    )


def has_any_role(role_ids):
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        user_role_ids = {r.id for r in interaction.user.roles}
        return bool(user_role_ids & set(role_ids))
    return app_commands.check(predicate)


def is_staff():
    return has_any_role(settings.STAFF_ROLE_IDS)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.temp_bans: list[dict] = self._load_temp_bans()
        self.check_temp_bans.start()
        # (guild_id, user_id) -> deque[(timestamp, содержимое сообщения в нижнем регистре)]
        self.recent_messages: dict[tuple[int, int], deque] = defaultdict(deque)
        # (guild_id, user_id), которые сейчас обрабатываются автомодерацией —
        # защита от повторного срабатывания, если участник шлёт несколько
        # сообщений почти одновременно (race condition)
        self._auto_moderating: set[tuple[int, int]] = set()

    def cog_unload(self):
        self.check_temp_bans.cancel()

    # ---------- temp_bans.json ----------
    def _load_temp_bans(self) -> list[dict]:
        if not os.path.exists(TEMP_BANS_FILE):
            return []
        try:
            with open(TEMP_BANS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("Не удалось прочитать %s, начинаю с пустого списка", TEMP_BANS_FILE)
            return []

    def _save_temp_bans(self):
        with open(TEMP_BANS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.temp_bans, f, ensure_ascii=False, indent=2)

    # ---------- вспомогательное форматирование ----------
    @staticmethod
    def _moderator_label(moderator) -> str:
        if moderator is None:
            return "Бот (автомодерация)"
        return f"{moderator} ({moderator.id})"

    def build_dm_embed(self, *, guild, action, moderator, reason, duration_text):
        embed = discord.Embed(title=action, color=EMBED_COLOR, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Сервер", value=guild.name, inline=False)
        embed.add_field(name="Модератор", value=self._moderator_label(moderator), inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Срок", value=duration_text, inline=False)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed

    @staticmethod
    async def _dm_user(user, embed: discord.Embed):
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            log.info("Не удалось отправить ЛС пользователю %s (закрыты личные сообщения)", user.id)

    async def _log_action(self, guild, channel_id, *, title, moderator, target, reason, duration_text, color):
        channel = guild.get_channel(channel_id)
        if channel is None:
            log.warning("Канал логов %s не найден", channel_id)
            return
        embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Участник", value=f"{target} ({target.id})", inline=False)
        embed.add_field(name="Модератор", value=self._moderator_label(moderator), inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Срок", value=duration_text, inline=False)
        await channel.send(embed=embed)

    @staticmethod
    async def _send_public_result(interaction: discord.Interaction, *, title, target, moderator, reason, duration_text):
        embed = discord.Embed(title=title, color=EMBED_COLOR, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Участник", value=target.mention if hasattr(target, "mention") else str(target), inline=False)
        embed.add_field(name="Модератор", value=moderator.mention, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Срок", value=duration_text, inline=False)
        await interaction.followup.send(embed=embed)

    # ---------- /ban ----------
    @app_commands.command(name="ban", description="Забанить участника на выбранный срок")
    @app_commands.describe(
        user="Кого забанить",
        reason="Причина бана",
        duration="Срок: 10m, 2h, 3d, 1w или 'навсегда' (по умолчанию — навсегда)",
    )
    @is_staff()
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: str, duration: str = "навсегда"):
        try:
            delta = parse_duration(duration)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        duration_text = format_duration(delta)

        embed = self.build_dm_embed(
            guild=interaction.guild, action="Вы были забанены", moderator=interaction.user,
            reason=reason, duration_text=duration_text,
        )
        await self._dm_user(user, embed)

        await interaction.guild.ban(user, reason=f"{reason} | Модератор: {interaction.user}")

        if delta is not None:
            unban_at = datetime.now(timezone.utc) + delta
            self.temp_bans.append({
                "user_id": user.id, "guild_id": interaction.guild.id,
                "unban_at": unban_at.isoformat(), "reason": reason,
            })
            self._save_temp_bans()

        await self._send_public_result(
            interaction, title="🔨 Участник забанен", target=user, moderator=interaction.user,
            reason=reason, duration_text=duration_text,
        )
        await self._log_action(
            interaction.guild, settings.BAN_LOG_CHANNEL_ID, title="Бан",
            moderator=interaction.user, target=user, reason=reason,
            duration_text=duration_text, color=EMBED_COLOR,
        )

    # ---------- /unban ----------
    @app_commands.command(name="unban", description="Разбанить участника по ID")
    @app_commands.describe(user_id="ID участника", reason="Причина разбана")
    @is_staff()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str):
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("ID должен быть числом.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{reason} | Модератор: {interaction.user}")
        except discord.NotFound:
            await interaction.followup.send("Этот пользователь не забанен.", ephemeral=True)
            return

        self.temp_bans = [
            b for b in self.temp_bans
            if not (b["user_id"] == uid and b["guild_id"] == interaction.guild.id)
        ]
        self._save_temp_bans()

        await self._send_public_result(
            interaction, title="🔓 Участник разбанен", target=user, moderator=interaction.user,
            reason=reason, duration_text="—",
        )
        await self._log_action(
            interaction.guild, settings.BAN_LOG_CHANNEL_ID, title="Разбан",
            moderator=interaction.user, target=user, reason=reason,
            duration_text="—", color=EMBED_COLOR,
        )

    # ---------- /mute ----------
    @app_commands.command(name="mute", description="Замьютить участника на выбранный срок (максимум 28 дней)")
    @app_commands.describe(
        user="Кого замьютить", reason="Причина мьюта",
        duration="Срок: 10m, 2h, 3d (максимум 28d — лимит Discord)",
    )
    @is_staff()
    async def mute(self, interaction: discord.Interaction, user: discord.Member, reason: str, duration: str):
        try:
            delta = parse_duration(duration)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        if delta is None:
            await interaction.response.send_message(
                "Мьют не может быть навсегда — максимум 28 дней (ограничение Discord API).", ephemeral=True
            )
            return

        note = ""
        if delta > timedelta(days=28):
            delta = timedelta(days=28)
            note = " (сокращено до 28 дней — лимит Discord API)"

        await interaction.response.defer(ephemeral=False)
        duration_text = format_duration(delta) + note

        embed = self.build_dm_embed(
            guild=interaction.guild, action="Вы были замьючены", moderator=interaction.user,
            reason=reason, duration_text=duration_text,
        )
        await self._dm_user(user, embed)

        await user.timeout(delta, reason=f"{reason} | Модератор: {interaction.user}")

        public_embed = discord.Embed(title="🔇 Участник замьючен", color=EMBED_COLOR, timestamp=datetime.now(timezone.utc))
        public_embed.add_field(name="Участник", value=user.mention, inline=False)
        public_embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)
        public_embed.add_field(name="Причина", value=reason, inline=False)
        public_embed.add_field(name="Срок", value=duration_text, inline=False)
        await interaction.followup.send(embed=public_embed)
        await self._log_action(
            interaction.guild, settings.MUTE_LOG_CHANNEL_ID, title="Мьют",
            moderator=interaction.user, target=user, reason=reason,
            duration_text=duration_text, color=EMBED_COLOR,
        )

    # ---------- /unmute ----------
    @app_commands.command(name="unmute", description="Снять мьют с участника")
    @app_commands.describe(user="С кого снять мьют", reason="Причина снятия мьюта")
    @is_staff()
    async def unmute(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        await interaction.response.defer(ephemeral=False)
        await user.timeout(None, reason=f"{reason} | Модератор: {interaction.user}")

        embed = self.build_dm_embed(
            guild=interaction.guild, action="С вас сняли мьют", moderator=interaction.user,
            reason=reason, duration_text="—",
        )
        await self._dm_user(user, embed)

        await self._send_public_result(
            interaction, title="🔊 Мьют снят", target=user, moderator=interaction.user,
            reason=reason, duration_text="—",
        )
        await self._log_action(
            interaction.guild, settings.MUTE_LOG_CHANNEL_ID, title="Снятие мьюта",
            moderator=interaction.user, target=user, reason=reason,
            duration_text="—", color=EMBED_COLOR,
        )

    # ---------- /server ----------
    @app_commands.command(name="server", description="Статистика сервера")
    @is_staff()
    async def server(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=f"Статистика {guild.name}", color=EMBED_COLOR)
        embed.add_field(name="Участники", value=str(guild.member_count))
        embed.add_field(name="Каналы", value=str(len(guild.channels)))
        embed.add_field(name="Роли", value=str(len(guild.roles)))
        embed.add_field(name="Бусты", value=str(guild.premium_subscription_count or 0))
        embed.add_field(name="Дата создания", value=discord.utils.format_dt(guild.created_at, style="D"), inline=False)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=embed)

    # ---------- /profile ----------
    @app_commands.command(name="profile", description="Показать профиль участника")
    @app_commands.describe(user="Чей профиль показать (по умолчанию — твой)")
    @has_any_role(PROFILE_ROLE_IDS)
    async def profile(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        embed = discord.Embed(title=f"Профиль {target.display_name}", color=EMBED_COLOR, timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Участник", value=f"{target} ({target.id})", inline=False)
        embed.add_field(name="Аккаунт создан", value=discord.utils.format_dt(target.created_at, style="D"), inline=True)
        embed.add_field(name="На сервере с", value=discord.utils.format_dt(target.joined_at, style="D") if target.joined_at else "—", inline=True)
        roles = [r.mention for r in target.roles if r.name != "@everyone"]
        embed.add_field(name="Роли", value=", ".join(roles) if roles else "—", inline=False)
        await interaction.response.send_message(embed=embed)

    # ---------- /очистить ----------
    @app_commands.command(name="очистить", description="Удалить указанное количество сообщений в этом канале")
    @app_commands.describe(количество="Сколько сообщений удалить (1-100)")
    @is_staff()
    async def clear(self, interaction: discord.Interaction, количество: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=False)
        deleted = await interaction.channel.purge(limit=количество)
        embed = discord.Embed(title="🧹 Сообщения удалены", color=EMBED_COLOR, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Удалено сообщений", value=str(len(deleted)), inline=False)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)
        await interaction.followup.send(embed=embed)
        log.info("%s удалил %s сообщений в #%s", interaction.user, len(deleted), interaction.channel)

    # ---------- обработчик ошибок слэш-команд когa ----------
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = "У тебя нет прав для этой команды."
        elif isinstance(error, discord.Forbidden):
            msg = "У бота недостаточно прав (проверь Ban Members / Moderate Members / Manage Messages и позицию роли бота)."
        else:
            msg = f"Произошла ошибка: {error}"
            log.exception("Ошибка команды модерации", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    # ---------- фоновая задача: снятие временных банов ----------
    @tasks.loop(minutes=1)
    async def check_temp_bans(self):
        now = datetime.now(timezone.utc)
        still_banned = []
        for entry in self.temp_bans:
            unban_at = datetime.fromisoformat(entry["unban_at"])
            if unban_at > now:
                still_banned.append(entry)
                continue
            guild = self.bot.get_guild(entry["guild_id"])
            if guild is None:
                continue
            try:
                user = await self.bot.fetch_user(entry["user_id"])
                await guild.unban(user, reason="Истёк срок временного бана")
                log.info("Автоматически разбанен %s на сервере %s", user.id, guild.id)
            except discord.NotFound:
                pass
            except discord.HTTPException as e:
                log.warning("Не удалось автоматически разбанить %s: %s", entry["user_id"], e)
                still_banned.append(entry)
        if len(still_banned) != len(self.temp_bans):
            self.temp_bans = still_banned
            self._save_temp_bans()

    @check_temp_bans.before_loop
    async def before_check_temp_bans(self):
        await self.bot.wait_until_ready()

    # ---------- общий автомьют (используется автомодерацией) ----------
    async def _auto_mute(self, message: discord.Message, reason: str, duration: timedelta, delete_message: bool = True):
        if delete_message:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass

        embed = self.build_dm_embed(
            guild=message.guild, action="Вы были замьючены", moderator=None,
            reason=reason, duration_text=format_duration(duration),
        )
        await self._dm_user(message.author, embed)

        try:
            await message.author.timeout(duration, reason=reason)
        except discord.Forbidden:
            log.warning("Не удалось замьютить %s: недостаточно прав", message.author.id)
            return
        except discord.HTTPException:
            # участник уже замьючен дольше — не продлеваем и не дублируем действия
            return

        await self._log_action(
            message.guild, settings.MUTE_LOG_CHANNEL_ID, title="Автомьют",
            moderator=None, target=message.author, reason=reason,
            duration_text=format_duration(duration), color=EMBED_COLOR,
        )

        public_embed = discord.Embed(title="🔇 Участник замьючен", color=EMBED_COLOR, timestamp=datetime.now(timezone.utc))
        public_embed.add_field(name="Участник", value=message.author.mention, inline=False)
        public_embed.add_field(name="Модератор", value="Бот (автомодерация)", inline=False)
        public_embed.add_field(name="Причина", value=reason, inline=False)
        public_embed.add_field(name="Срок", value=format_duration(duration), inline=False)
        try:
            await message.channel.send(embed=public_embed)
        except discord.Forbidden:
            log.warning("Не удалось отправить публичное сообщение об автомьюте в канал %s", message.channel.id)

        # сбрасываем историю сообщений участника, чтобы не триггерить спам-детект повторно,
        # пока действует мьют
        self.recent_messages.pop((message.guild.id, message.author.id), None)

    async def _try_auto_mute(self, message: discord.Message, *, reason: str, duration: timedelta) -> bool:
        """Атомарно проверяет и ставит блокировку, чтобы одно и то же превышение
        лимита (пришедшее в виде нескольких почти одновременных сообщений)
        не вызвало мьют/лог/публичный эмбед несколько раз подряд."""
        key = (message.guild.id, message.author.id)
        if key in self._auto_moderating:
            return False
        self._auto_moderating.add(key)
        try:
            await self._auto_mute(message, reason=reason, duration=duration)
        finally:
            self._auto_moderating.discard(key)
        return True

    # ---------- автомодерация: инвайты, спам, пинг-спам ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not isinstance(message.author, discord.Member):
            return

        role_ids = {r.id for r in message.author.roles}
        if role_ids & set(settings.STAFF_ROLE_IDS):
            return  # стафф и администраторы исключены

        if (message.guild.id, message.author.id) in self._auto_moderating:
            return  # уже мьютим этого участника прямо сейчас — не дублируем

        auto_mute_duration = timedelta(minutes=10)

        # ---- 1. ссылки-приглашения на чужие Discord-серверы ----
        invite_re = re.compile(r"(?:discord\.gg/|discord(?:app)?\.com/invite/)(\S+)", re.IGNORECASE)
        found_codes = invite_re.findall(message.content)
        if found_codes:
            try:
                server_invites = {inv.code for inv in await message.guild.invites()}
            except discord.Forbidden:
                server_invites = set()

            if not all(code in server_invites for code in found_codes):
                await self._try_auto_mute(
                    message,
                    reason="Присылание ссылок - приглашений на чужой Discord сервер",
                    duration=auto_mute_duration,
                )
                return

        # ---- 2. спам пингами (много упоминаний в одном сообщении) ----
        mention_count = len(message.mentions) + len(message.role_mentions) + (1 if message.mention_everyone else 0)
        if mention_count >= SPAM_MENTION_LIMIT:
            await self._try_auto_mute(
                message,
                reason=f"Спам пингами ({mention_count} упоминаний в одном сообщении)",
                duration=auto_mute_duration,
            )
            return

        # ---- 3. флуд и повторяющиеся сообщения ----
        key = (message.guild.id, message.author.id)
        now = datetime.now(timezone.utc)
        content_key = message.content.strip().lower()

        history = self.recent_messages[key]
        history.append((now, content_key))
        while history and (now - history[0][0]).total_seconds() > SPAM_DUPLICATE_WINDOW:
            history.popleft()

        flood_recent = [t for t, _ in history if (now - t).total_seconds() <= SPAM_FLOOD_WINDOW]
        if len(flood_recent) >= SPAM_FLOOD_COUNT:
            await self._try_auto_mute(
                message,
                reason=f"Спам сообщениями ({len(flood_recent)} сообщений за {SPAM_FLOOD_WINDOW} сек.)",
                duration=auto_mute_duration,
            )
            return

        if content_key:
            duplicates = [c for _, c in history if c == content_key]
            if len(duplicates) >= SPAM_DUPLICATE_COUNT:
                await self._try_auto_mute(
                    message,
                    reason="Спам одинаковыми сообщениями",
                    duration=auto_mute_duration,
                )
                return


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
