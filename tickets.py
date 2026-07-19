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
прикреплёнными файлами (доказательствами). Открытый тикет создаётся в своей категории
(своя для «Жалобы на игрока» и своя для «Жалобы на персонал»).

Внутри открытого тикета есть две кнопки:
- «Рассмотреть» — отправляет в канал эмбед с уведомлением, что заявку рассматривает
  администратор (с пингом того, кто нажал кнопку).
- «Закрыть тикет» — не удаляет канал, а переносит его в соответствующую категорию для
  закрытых тикетов и закрывает доступ к каналу автору тикета и ролям из
  settings.TICKET_CLOSED_HIDDEN_ROLE_IDS. После закрытия автор тикета может создать
  новый тикет того же типа.

Открытие и закрытие тикетов подробно логируются в settings.TICKET_LOG_CHANNEL_ID
(кто создал, по какой причине, кто закрыл).
"""

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
TICKET_REVIEW_BUTTON_CUSTOM_ID = "evalens:ticket_review"
PLAYER_REPORT_BUTTON_CUSTOM_ID = "evalens:ticket_player_report"
STAFF_REPORT_BUTTON_CUSTOM_ID = "evalens:ticket_staff_report"

# Соответствие "категория для открытых тикетов" -> "категория для закрытых тикетов",
# используется при закрытии, чтобы понять, куда переносить канал.
CLOSED_CATEGORY_BY_OPEN = {
    settings.PLAYER_REPORT_OPEN_CATEGORY_ID: settings.PLAYER_REPORT_CLOSED_CATEGORY_ID,
    settings.STAFF_REPORT_OPEN_CATEGORY_ID: settings.STAFF_REPORT_CLOSED_CATEGORY_ID,
}


def _is_staff(user: discord.abc.User) -> bool:
    return isinstance(user, discord.Member) and bool(
        {r.id for r in user.roles} & set(settings.STAFF_ROLE_IDS)
    )


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
            channel_prefix="player-report",
            open_category_id=settings.PLAYER_REPORT_OPEN_CATEGORY_ID,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.exception("Ошибка в модалке «Жалоба на игрока»", exc_info=error)
        msg = "Что-то пошло не так при создании тикета. Попробуйте ещё раз."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


# ---------- модальное окно «Жалоба на персонал» ----------
class StaffReportModal(ui.Modal, title="Жалоба на персонал"):
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
    staff_position = ui.Label(
        text="Должность сотрудника",
        description="Введите должность сотрудника",
        component=ui.TextInput(placeholder="Введите должность сотрудника", max_length=100),
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
            category="Жалоба на персонал",
            emoji="🚨",
            fields={
                "Ваш ник": self.reporter_nick.component.value,
                "Ник нарушителя": self.offender_nick.component.value,
                "Должность сотрудника": self.staff_position.component.value,
                "Причина": self.reason.component.value,
            },
            attachments=self.proof.component.values or [],
            channel_prefix="staff-report",
            open_category_id=settings.STAFF_REPORT_OPEN_CATEGORY_ID,
            ping_role_ids=settings.STAFF_REPORT_PING_ROLE_IDS,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.exception("Ошибка в модалке «Жалоба на персонал»", exc_info=error)
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

    @ui.button(
        label="Жалоба на персонал",
        style=discord.ButtonStyle.secondary,
        emoji="🚨",
        custom_id=STAFF_REPORT_BUTTON_CUSTOM_ID,
    )
    async def staff_report(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(StaffReportModal(self.cog))


# ---------- кнопки внутри канала тикета: "Рассмотреть" и "Закрыть тикет" ----------
class TicketActionsView(ui.View):
    def __init__(self, cog: "Tickets" = None):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(
        label="Рассмотреть",
        style=discord.ButtonStyle.primary,
        emoji="🔍",
        custom_id=TICKET_REVIEW_BUTTON_CUSTOM_ID,
    )
    async def review_ticket(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Рассмотреть тикет может только стафф.", ephemeral=True)
            return

        embed = discord.Embed(
            description=f"🔍 Вашу заявку рассматривает администратор {interaction.user.mention}",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )

        await interaction.response.send_message(content=interaction.user.mention, embed=embed)
        log.info("%s начал рассмотрение тикета %s", interaction.user, interaction.channel.id)

        cog = self.cog or interaction.client.get_cog("Tickets")
        if cog is not None:
            await cog.log_ticket_event(
                interaction.guild,
                title="Тикет взят на рассмотрение",
                color=discord.Color(0x808080),
                fields=[
                    ("Канал", interaction.channel.mention, True),
                    ("Администратор", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ],
            )

    @ui.button(
        label="Закрыть тикет",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id=TICKET_CLOSE_BUTTON_CUSTOM_ID,
    )
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Закрыть тикет может только стафф.", ephemeral=True)
            return

        channel = interaction.channel
        cog = self.cog or interaction.client.get_cog("Tickets")

        # определяем автора тикета (сохранён в topic канала при создании)
        owner_id = None
        if channel.topic and channel.topic.isdigit():
            owner_id = int(channel.topic)
        owner = interaction.guild.get_member(owner_id) if owner_id else None

        # собираем подробности тикета (тип, ник, причину и т.д.) из исходного эмбеда,
        # чтобы отправить их в лог
        ticket_info = await cog.extract_ticket_info(channel) if cog is not None else None

        # переносим канал в категорию "закрытые тикеты", соответствующую его текущей
        current_category_id = channel.category_id
        closed_category_id = CLOSED_CATEGORY_BY_OPEN.get(current_category_id)
        closed_category = None
        if closed_category_id:
            maybe_category = interaction.guild.get_channel(closed_category_id)
            if isinstance(maybe_category, discord.CategoryChannel):
                closed_category = maybe_category

        # закрываем доступ к каналу автору тикета и указанным ролям (архив им больше не виден)
        try:
            if owner is not None:
                await channel.set_permissions(
                    owner,
                    view_channel=False,
                    reason=f"Тикет закрыт: {interaction.user}",
                )

            for role_id in settings.TICKET_CLOSED_HIDDEN_ROLE_IDS:
                role = interaction.guild.get_role(role_id)
                if role is not None:
                    await channel.set_permissions(
                        role,
                        view_channel=False,
                        reason=f"Тикет закрыт: {interaction.user}",
                    )

            if closed_category is not None:
                await channel.edit(
                    category=closed_category,
                    sync_permissions=False,
                    reason=f"Тикет закрыт: {interaction.user}",
                )
            else:
                log.warning(
                    "Не найдена категория для закрытых тикетов (текущая категория %s), канал %s не перенесён",
                    current_category_id, channel.id,
                )
        except discord.Forbidden:
            log.warning("Недостаточно прав, чтобы перенести/закрыть канал тикета %s", channel.id)
        except discord.HTTPException:
            log.exception("Ошибка при закрытии канала тикета %s", channel.id)

        # отключаем кнопки в исходном сообщении
        for child in self.children:
            child.disabled = True
        button.label = "Тикет закрыт"
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"🔒 Тикет закрыт участником {interaction.user.mention}.",
                )

        await channel.send(f"🔒 Тикет закрыт участником {interaction.user.mention}.")
        log.info("%s закрыл тикет %s", interaction.user, channel.id)

        if cog is not None:
            log_fields = [
                ("Закрыл", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Канал", f"{channel.name} (`{channel.id}`)", True),
            ]
            if ticket_info:
                log_fields.append(("Тип тикета", ticket_info.get("type", "неизвестно"), True))
                if owner is not None:
                    log_fields.append(("Автор тикета", f"{owner.mention} (`{owner.id}`)", True))
                elif owner_id:
                    log_fields.append(("Автор тикета", f"`{owner_id}` (покинул сервер)", True))
                for name, value in ticket_info.get("details", {}).items():
                    log_fields.append((name, value or "—", False))
            elif owner is not None:
                log_fields.append(("Автор тикета", f"{owner.mention} (`{owner.id}`)", True))

            await cog.log_ticket_event(
                interaction.guild,
                title="Тикет закрыт",
                color=discord.Color(0x808080),
                fields=log_fields,
            )


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketActionsView(self))
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

    @staticmethod
    async def extract_ticket_info(channel: discord.TextChannel) -> dict | None:
        """Достаёт тип тикета и поля анкеты из первого эмбед-сообщения в канале."""
        try:
            async for message in channel.history(limit=10, oldest_first=True):
                if message.author.bot and message.embeds:
                    embed = message.embeds[0]
                    return {
                        "type": (embed.title or "").strip(),
                        "details": {f.name: f.value for f in embed.fields},
                    }
        except discord.HTTPException:
            log.exception("Не удалось прочитать историю канала %s для лога", channel.id)
        return None

    async def log_ticket_event(
        self,
        guild: discord.Guild,
        *,
        title: str,
        color: discord.Color,
        fields: list[tuple[str, str, bool]],
    ):
        if not settings.TICKET_LOG_CHANNEL_ID:
            return
        channel = guild.get_channel(settings.TICKET_LOG_CHANNEL_ID)
        if channel is None:
            log.warning("Канал логов тикетов %s не найден", settings.TICKET_LOG_CHANNEL_ID)
            return
        embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
        for name, value, inline in fields:
            # эмбед-поле ограничено 1024 символами
            embed.add_field(name=name[:256], value=(str(value) or "—")[:1024], inline=inline)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Не удалось отправить лог тикета в канал %s", channel.id)

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
            embed.add_field(
                name="Жалоба на Персонал 🚨",
                value="Тут вы можете подать жалобу на Персонал за нарушение правил в Дискорде или в игре",
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
        channel_prefix: str,
        open_category_id: int,
        ping_role_ids: set[int] | None = None,
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

        ticket_category = guild.get_channel(open_category_id) if open_category_id else None
        if not isinstance(ticket_category, discord.CategoryChannel):
            ticket_category = None
            log.warning("Категория для открытых тикетов %s не найдена", open_category_id)

        # ищем уже открытый тикет этого же типа у пользователя (только среди каналов
        # в категории "открытые" — закрытые тикеты не мешают создать новый)
        existing = None
        if ticket_category is not None:
            for ch in ticket_category.text_channels:
                if ch.topic == str(interaction.user.id):
                    existing = ch
                    break
        if existing is not None:
            await interaction.followup.send(f"У вас уже есть открытый тикет: {existing.mention}", ephemeral=True)
            return

        channel_name = self._channel_name(channel_prefix, interaction.user)

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

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=ticket_category,
                overwrites=overwrites,
                topic=str(interaction.user.id),  # используется при закрытии/повторной проверке
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

        if ping_role_ids:
            # для этого типа тикета пингуются только явно указанные роли
            mention_roles = []
            for role_id in ping_role_ids:
                role = guild.get_role(role_id)
                if role is not None:
                    mention_roles.append(role)
            staff_mentions = " ".join(role.mention for role in mention_roles)
        else:
            staff_mentions = " ".join(
                role.mention for role in staff_roles if role.id not in settings.TICKET_NO_PING_ROLE_IDS
            )

        try:
            await channel.send(
                content=f"{interaction.user.mention} {staff_mentions}".strip(),
                embed=embed,
                files=files,
                view=TicketActionsView(self),
            )
        except discord.HTTPException:
            log.exception("Не удалось отправить сообщение в тикет-канал %s", channel.id)

        self._record_ticket(interaction.user.id)
        await interaction.followup.send(f"✅ Тикет создан: {channel.mention}", ephemeral=True)
        log.info("Создан тикет «%s» для %s (канал %s)", category, interaction.user, channel.id)

        log_fields = [
            ("Тип тикета", category, True),
            ("Автор", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
            ("Канал", channel.mention, True),
        ]
        for name, value in fields.items():
            log_fields.append((name, value, False))

        await self.log_ticket_event(
            guild,
            title="Тикет открыт",
            color=discord.Color(0x808080),
            fields=log_fields,
        )

    @staticmethod
    def _channel_name(prefix: str, user: discord.abc.User) -> str:
        safe_name = "".join(c for c in user.name.lower() if c.isalnum() or c == "-")[:20] or str(user.id)
        return f"{prefix}-{safe_name}"


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
