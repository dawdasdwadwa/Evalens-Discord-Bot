"""
moderation.py — слэш-команды модерации: /ban, /kick, /mute, /unban, /unmute, /server.

Доступ:
    Команды может использовать только участник, у которого есть хотя бы
    одна из ролей ALLOWED_ROLE_IDS.

Временные баны:
    У Discord API нет встроенного "бана на время" — только вечный бан.
    Поэтому временный бан реализован вручную: при бане с указанным сроком
    запись сохраняется в temp_bans.json, а фоновая задача (каждую минуту)
    проверяет, не истёк ли срок, и снимает бан автоматически.
    ВАЖНО: если Railway у тебя без подключённого Volume, файловая система
    эфемерна — при редеплое temp_bans.json обнулится и все текущие
    временные баны "зависнут" забаненными навсегда (придётся /unban
    вручную). Если временные баны нужны железно — подключи Railway Volume
    и укажи в нём путь для TEMP_BANS_FILE.

Мут:
    Реализован через встроенный Discord timeout (member.timeout(...)).
    Максимум, который разрешает сам Discord — 28 дней. Поэтому в /mute
    нет варианта "навсегда": это ограничение платформы, не бота.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

ALLOWED_ROLE_IDS = {
    1527719775114105073,
    1527719636420919396,
    1527719311970668716,
    1527718985485910016,
}

TEMP_BANS_FILE = "temp_bans.json"

BAN_DURATION_CHOICES = [
    app_commands.Choice(name="1 час", value="1h"),
    app_commands.Choice(name="1 день", value="1d"),
    app_commands.Choice(name="3 дня", value="3d"),
    app_commands.Choice(name="7 дней", value="7d"),
    app_commands.Choice(name="30 дней", value="30d"),
    app_commands.Choice(name="Навсегда", value="permanent"),
]

MUTE_DURATION_CHOICES = [
    app_commands.Choice(name="5 минут", value="5m"),
    app_commands.Choice(name="10 минут", value="10m"),
    app_commands.Choice(name="30 минут", value="30m"),
    app_commands.Choice(name="1 час", value="1h"),
    app_commands.Choice(name="6 часов", value="6h"),
    app_commands.Choice(name="12 часов", value="12h"),
    app_commands.Choice(name="1 день", value="1d"),
    app_commands.Choice(name="7 дней", value="7d"),
    app_commands.Choice(name="28 дней (максимум Discord)", value="28d"),
]

_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


def parse_duration(value: str) -> timedelta | None:
    """'1h' / '7d' / '30m' -> timedelta. 'permanent' или '' -> None."""
    if not value or value == "permanent":
        return None
    unit = value[-1]
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"Неизвестный формат длительности: {value}")
    amount = int(value[:-1])
    return timedelta(seconds=amount * _UNIT_SECONDS[unit])


def is_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        return any(role.id in ALLOWED_ROLE_IDS for role in member.roles)
    return app_commands.check(predicate)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.temp_bans: dict[str, dict[str, str]] = self._load_temp_bans()
        self.check_temp_bans.start()

    def cog_unload(self):
        self.check_temp_bans.cancel()

    # ---------- хранилище временных банов ----------

    def _load_temp_bans(self) -> dict:
        if os.path.exists(TEMP_BANS_FILE):
            try:
                with open(TEMP_BANS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Не удалось прочитать %s: %s", TEMP_BANS_FILE, e)
        return {}

    def _save_temp_bans(self) -> None:
        try:
            with open(TEMP_BANS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.temp_bans, f, indent=2)
        except OSError as e:
            logger.warning("Не удалось сохранить %s: %s", TEMP_BANS_FILE, e)

    def _key(self, guild_id: int, user_id: int) -> str:
        return f"{guild_id}:{user_id}"

    @tasks.loop(minutes=1)
    async def check_temp_bans(self):
        now = datetime.now(timezone.utc)
        expired_keys = []

        for key, data in list(self.temp_bans.items()):
            unban_at = datetime.fromisoformat(data["unban_at"])
            if now < unban_at:
                continue

            guild_id = int(data["guild_id"])
            user_id = int(data["user_id"])
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                expired_keys.append(key)
                continue

            try:
                await guild.unban(
                    discord.Object(id=user_id),
                    reason="Истёк срок временного бана",
                )
                logger.info("Автоматически разбанен %s на сервере %s", user_id, guild_id)
            except discord.NotFound:
                pass  # уже разбанен вручную
            except discord.HTTPException as e:
                logger.warning("Не удалось авто-разбанить %s: %s", user_id, e)
            expired_keys.append(key)

        if expired_keys:
            for key in expired_keys:
                self.temp_bans.pop(key, None)
            self._save_temp_bans()

    @check_temp_bans.before_loop
    async def before_check_temp_bans(self):
        await self.bot.wait_until_ready()

    # ---------- общий обработчик ошибок для когa ----------

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "У тебя нет прав для использования этой команды.", ephemeral=True
            )
            return

        logger.exception("Ошибка в команде модерации", exc_info=error)
        message = f"Произошла ошибка: {error}"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # ---------- /ban ----------

    @app_commands.command(name="ban", description="Забанить участника")
    @app_commands.describe(
        member="Кого забанить",
        reason="Причина бана",
        duration="На сколько банить (по умолчанию — навсегда)",
    )
    @app_commands.choices(duration=BAN_DURATION_CHOICES)
    @is_staff()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Причина не указана",
        duration: app_commands.Choice[str] | None = None,
    ):
        guild = interaction.guild
        assert guild is not None

        if member.top_role >= guild.me.top_role:
            await interaction.response.send_message(
                "Не могу забанить этого участника — его роль выше или равна роли бота.",
                ephemeral=True,
            )
            return

        delta = parse_duration(duration.value) if duration else None

        try:
            await member.send(
                f"Ты был(а) забанен(а) на сервере **{guild.name}**.\n"
                f"Причина: {reason}\n"
                f"Срок: {'навсегда' if delta is None else duration.name}"
            )
        except discord.HTTPException:
            pass  # ЛС закрыты — это нормально, продолжаем

        await guild.ban(member, reason=reason, delete_message_seconds=0)

        if delta is not None:
            unban_at = datetime.now(timezone.utc) + delta
            self.temp_bans[self._key(guild.id, member.id)] = {
                "guild_id": str(guild.id),
                "user_id": str(member.id),
                "unban_at": unban_at.isoformat(),
            }
            self._save_temp_bans()

        embed = discord.Embed(
            title="Участник забанен",
            color=0x808080,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Срок", value="Навсегда" if delta is None else duration.name, inline=False)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- /kick ----------

    @app_commands.command(name="kick", description="Кикнуть участника с сервера")
    @app_commands.describe(member="Кого кикнуть", reason="Причина кика")
    @is_staff()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Причина не указана",
    ):
        guild = interaction.guild
        assert guild is not None

        if member.top_role >= guild.me.top_role:
            await interaction.response.send_message(
                "Не могу кикнуть этого участника — его роль выше или равна роли бота.",
                ephemeral=True,
            )
            return

        try:
            await member.send(
                f"Ты был(а) кикнут(а) с сервера **{guild.name}**.\nПричина: {reason}"
            )
        except discord.HTTPException:
            pass

        await guild.kick(member, reason=reason)

        embed = discord.Embed(
            title="Участник кикнут",
            color=0x808080,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- /unban ----------

    @app_commands.command(name="unban", description="Разбанить участника по ID")
    @app_commands.describe(user_id="ID участника, которого нужно разбанить", reason="Причина разбана")
    @is_staff()
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: str = "Причина не указана",
    ):
        guild = interaction.guild
        assert guild is not None

        if not user_id.isdigit():
            await interaction.response.send_message(
                "ID должен состоять только из цифр. Скопировать ID можно через "
                "Настройки Discord → Расширенные → Режим разработчика, затем ПКМ по пользователю.",
                ephemeral=True,
            )
            return

        user = discord.Object(id=int(user_id))

        try:
            await guild.fetch_ban(user)
        except discord.NotFound:
            await interaction.response.send_message(
                "Этот пользователь не забанен на сервере.", ephemeral=True
            )
            return

        await guild.unban(user, reason=reason)
        self.temp_bans.pop(self._key(guild.id, int(user_id)), None)
        self._save_temp_bans()

        embed = discord.Embed(
            title="Участник разбанен",
            color=0x808080,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="ID участника", value=f"`{user_id}`", inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- /mute ----------

    @app_commands.command(name="mute", description="Замьютить участника (timeout)")
    @app_commands.describe(
        member="Кого замьютить",
        duration="На сколько замьютить",
        reason="Причина мьюта",
    )
    @app_commands.choices(duration=MUTE_DURATION_CHOICES)
    @is_staff()
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: app_commands.Choice[str],
        reason: str = "Причина не указана",
    ):
        guild = interaction.guild
        assert guild is not None

        if member.top_role >= guild.me.top_role:
            await interaction.response.send_message(
                "Не могу замьютить этого участника — его роль выше или равна роли бота.",
                ephemeral=True,
            )
            return

        delta = parse_duration(duration.value)
        until = discord.utils.utcnow() + delta

        await member.timeout(until, reason=reason)

        try:
            await member.send(
                f"Ты был(а) замьючен(а) на сервере **{guild.name}**.\n"
                f"Причина: {reason}\nСрок: {duration.name}"
            )
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title="Участник замьючен",
            color=0x808080,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Срок", value=duration.name, inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- /unmute ----------

    @app_commands.command(name="unmute", description="Снять мьют с участника")
    @app_commands.describe(member="С кого снять мьют", reason="Причина снятия мьюта")
    @is_staff()
    async def unmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Причина не указана",
    ):
        if member.timed_out_until is None:
            await interaction.response.send_message(
                "Этот участник не замьючен.", ephemeral=True
            )
            return

        await member.timeout(None, reason=reason)

        embed = discord.Embed(
            title="Мьют снят",
            color=0x808080,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- /server ----------

    @app_commands.command(name="server", description="Показать статистику сервера")
    @is_staff()
    async def server(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None

        if guild.member_count is None:
            await guild.chunk()

        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)

        created_ts = int(guild.created_at.timestamp())

        embed = discord.Embed(
            title=guild.name,
            color=0x808080,
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="ID сервера", value=f"`{guild.id}`", inline=False)
        embed.add_field(name="Владелец", value=f"{guild.owner.mention if guild.owner else 'неизвестно'}", inline=True)
        embed.add_field(name="Создан", value=f"<t:{created_ts}:D> (<t:{created_ts}:R>)", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        embed.add_field(
            name="Участники",
            value=f"Всего: **{guild.member_count}**\nЛюди: **{humans}**\nБоты: **{bots}**\nОнлайн: **{online}**",
            inline=True,
        )
        embed.add_field(
            name="Каналы",
            value=f"Текстовые: **{text_channels}**\nГолосовые: **{voice_channels}**\nКатегории: **{categories}**",
            inline=True,
        )
        embed.add_field(
            name="Прочее",
            value=f"Роли: **{len(guild.roles)}**\nЭмодзи: **{len(guild.emojis)}**\nБуст-уровень: **{guild.premium_tier}**\nБустов: **{guild.premium_subscription_count}**",
            inline=True,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
