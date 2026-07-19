"""
Ког системы тикетов.

Панель с кнопками публикуется автоматически в канале settings.TICKETS_CHANNEL_ID
при каждом старте бота (старые сообщения бота в канале чистятся перед публикацией
новой панели — по тому же принципу, что и панель верификации).

При нажатии на кнопку открывается модальное окно (discord.ui.Modal с discord.ui.Label +
discord.ui.FileUpload — компонент загрузки файлов прямо в модалке, появился в Discord API
в 2025 году и требует discord.py>=2.7.0).

После отправки формы создаётся приватный текстовый канал-тикет, видимый только автору
обращения и ролям из settings.STAFF_ROLE_IDS, куда постится эмбед с ответами и
прикреплёнными файлами (доказательствами).
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import discord
from discord import ui
from discord.ext import commands

import settings

log = logging.getLogger("evalens.tickets")

EMBED_COLOR = discord.Color.light_grey()
TICKET_HISTORY_FILE = "ticket_history.json"

TICKET_CLOSE_BUTTON_CUSTOM_ID = "evalens:ticket_close"
PLAYER_REPORT_BUTTON_CUSTOM_ID = "evalens:ticket_player_report"


# ---------- модальное окно «Жалоба на игрока» ----------
class PlayerReportModal(ui.Modal, title="Жалоба на игрока"):
    reporter_nick = ui.Label(
        text="Ваш ник",
        description="Введите ваш роблокс ник / дискорд ник",
        component=ui.TextInput(placeholder="@username", max_length=100),
    )
    offender_nick = ui.Label(
        text="Ник нарушителя",
        description="Введите ник/айди роблокса/дискорда нарушителя",
        component=ui.TextInput(placeholder="@username", max_length=200),
    )
    reason = ui.Label(
        text="Причина",
        description="Введите причину",
        component=ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="Введите причину",
            max_length=1000,
        ),
    )
    proof = ui.Label(
        text="Доказательства",
        description="Прикрепите скриншоты или видео нарушения (необязательно)",
        component=ui.FileUpload(required=False, min_values=0, max_values=3),
    )

    def __init__(self, cog: "Tickets"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket(
            interaction,
            category="Жалоба на игрока",
            emoji="🛡️",
            fields={
                "Ваш ник": self.reporter_nick.component.value,
                "Ник нарушителя": self.offender_nick.component.value,
                "Причина": self.reason.component.value,
            },
            attachments=self.proof.component.values or [],
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.exception("Ошибка в модалке «Жалоба на игрока»", exc_info=error)
        msg = "Что-то пошло не так при создании тикета. Попробуйте ещё раз."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


# ---------- постоянная панель с кнопками ----------
class TicketPanelView(ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(
        label="Жалоба на игрока",
        style=discord.ButtonStyle.secondary,
        emoji="🛡️",
        custom_id=PLAYER_REPORT_BUTTON_CUSTOM_ID,
    )
    async def player_report(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PlayerReportModal(self.cog))


# ---------- кнопка закрытия тикета (внутри созданного канала) ----------
class TicketCloseView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="Закрыть тикет",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id=TICKET_CLOSE_BUTTON_CUSTOM_ID,
    )
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        role_ids = {r.id for r in interaction.user.roles} if isinstance(interaction.user, discord.Member) else set()
        if not (role_ids & set(settings.STAFF_ROLE_IDS)):
            await interaction.response.send_message("Закрыть тикет может только стафф.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"🔒 Тикет закрыт участником {interaction.user.mention}. Канал будет удалён через 5 секунд."
        )
        log.info("%s закрыл тикет %s", interaction.user, interaction.channel.id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Тикет закрыт: {interaction.user}")
        except discord.Forbidden:
            log.warning("Недостаточно прав, чтобы удалить канал тикета %s", interaction.channel.id)
        except discord.NotFound:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketCloseView())
        self._panel_posted = False
        # {user_id: [ISO-таймстемпы созданных тикетов]}
        self.ticket_history: dict[str, list[str]] = self._load_ticket_history()

    def _load_ticket_history(self) -> dict[str, list[str]]:
        if not os.path.exists(TICKET_HISTORY_FILE):
            return {}
        try:
            with open(TICKET_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("Не удалось прочитать %s, начинаю с пустой истории", TICKET_HISTORY_FILE)
            return {}

    def _save_ticket_history(self):
        with open(TICKET_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.ticket_history, f, ensure_ascii=False, indent=2)

    def _tickets_today(self, user_id: int) -> list[str]:
        """Возвращает и попутно чистит от устаревших записей список
        таймстемпов тикетов пользователя за последние 24 часа."""
        now = datetime.now(timezone.utc)
        key = str(user_id)
        entries = self.ticket_history.get(key, [])
        fresh = [ts for ts in entries if now - datetime.fromisoformat(ts) <= timedelta(hours=24)]
        if len(fresh) != len(entries):
            self.ticket_history[key] = fresh
            self._save_ticket_history()
        return fresh

    def _record_ticket(self, user_id: int):
        key = str(user_id)
        self.ticket_history.setdefault(key, []).append(datetime.now(timezone.utc).isoformat())
        self._save_ticket_history()

    @commands.Cog.listener()
    async def on_ready(self):
        if self._panel_posted:
            return
        self._panel_posted = True

        for guild in self.bot.guilds:
            channel = guild.get_channel(settings.TICKETS_CHANNEL_ID)
            if channel is None:
                log.warning("Канал тикетов %s не найден", settings.TICKETS_CHANNEL_ID)
                continue

            try:
                await channel.purge(limit=50, check=lambda m: m.author == self.bot.user)
            except discord.Forbidden:
                log.warning("Нет прав на очистку канала тикетов %s", channel.id)
            except discord.HTTPException:
                log.exception("Не удалось очистить канал тикетов %s", channel.id)

            embed = discord.Embed(title="Тикеты", color=EMBED_COLOR)
            embed.add_field(
                name="Жалоба на игрока 🛡️",
                value="Тут вы можете подать жалобу на игрока за нарушение в Дискорде или в игре",
                inline=False,
            )

            try:
                await channel.send(embed=embed, view=TicketPanelView(self))
                log.info("Панель тикетов опубликована в канале %s", channel.id)
            except discord.HTTPException:
                log.exception("Не удалось опубликовать панель тикетов в канале %s", channel.id)

    # ---------- создание тикета ----------
    async def create_ticket(
        self,
        interaction: discord.Interaction,
        *,
        category: str,
        emoji: str,
        fields: dict,
        attachments: list[discord.Attachment],
    ):
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Тикеты можно создавать только на сервере.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        recent = self._tickets_today(interaction.user.id)
        if len(recent) >= settings.TICKET_DAILY_LIMIT:
            await interaction.followup.send(
                f"Вы достигли лимита в {settings.TICKET_DAILY_LIMIT} тикетов за 24 часа. "
                f"Попробуйте позже.",
                ephemeral=True,
            )
            return

        channel_name = self._channel_name(interaction.user)
        existing = discord.utils.get(guild.text_channels, name=channel_name)
        if existing is not None:
            await interaction.followup.send(f"У вас уже есть открытый тикет: {existing.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
            ),
        }
        staff_roles = []
        for role_id in settings.STAFF_ROLE_IDS:
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )
                staff_roles.append(role)

        ticket_category = guild.get_channel(settings.TICKET_CATEGORY_ID) if settings.TICKET_CATEGORY_ID else None
        if not isinstance(ticket_category, discord.CategoryChannel):
            ticket_category = None

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=ticket_category,
                overwrites=overwrites,
                reason=f"Тикет «{category}» от {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "У бота недостаточно прав, чтобы создать канал тикета (нужно право Manage Channels).",
                ephemeral=True,
            )
            log.error("Недостаточно прав на создание канала тикета для %s", interaction.user)
            return

        embed = discord.Embed(
            title=f"{emoji} {category}", color=EMBED_COLOR, timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        for name, value in fields.items():
            embed.add_field(name=name, value=value or "—", inline=False)
        embed.set_footer(text=f"ID автора: {interaction.user.id}")

        files = []
        for att in attachments[:3]:
            try:
                files.append(await att.to_file())
            except discord.HTTPException:
                log.warning("Не удалось прикрепить файл %s к тикету", att.filename)

        staff_mentions = " ".join(
            role.mention for role in staff_roles if role.id not in settings.TICKET_NO_PING_ROLE_IDS
        )

        try:
            await channel.send(
                content=f"{interaction.user.mention} {staff_mentions}".strip(),
                embed=embed,
                files=files,
                view=TicketCloseView(),
            )
        except discord.HTTPException:
            log.exception("Не удалось отправить сообщение в тикет-канал %s", channel.id)

        self._record_ticket(interaction.user.id)
        await interaction.followup.send(f"✅ Тикет создан: {channel.mention}", ephemeral=True)
        log.info("Создан тикет «%s» для %s (канал %s)", category, interaction.user, channel.id)

    @staticmethod
    def _channel_name(user: discord.abc.User) -> str:
        safe_name = "".join(c for c in user.name.lower() if c.isalnum() or c == "-")[:20] or str(user.id)
        return f"ticket-{safe_name}"


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
