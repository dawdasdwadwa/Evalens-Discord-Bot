"""
Ког верификации участников по кнопке.

Панель верификации публикуется АВТОМАТИЧЕСКИ при каждом старте бота
(в т.ч. при редеплое) — без ручной команды. Старое сообщение бота
в канале верификации удаляется перед отправкой нового, чтобы панели
не копились при перезапусках.

Успешные верификации логируются в отдельный канал.
"""

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import settings

log = logging.getLogger("evalens.verification")

VERIFY_BUTTON_CUSTOM_ID = "evalens:verify_button"


class VerificationView(discord.ui.View):
    """Постоянная View с кнопкой верификации."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label=settings.VERIFICATION_BUTTON_LABEL,
        style=discord.ButtonStyle.secondary,  # Discord API не поддерживает чёрный цвет кнопки,
                                               # secondary (тёмно-серый) — самый близкий вариант
        emoji="🤍",
        custom_id=VERIFY_BUTTON_CUSTOM_ID,
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user

        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Эта кнопка работает только на сервере.", ephemeral=True
            )
            return

        if settings.VERIFIED_ROLE_ID == 0:
            await interaction.response.send_message(
                "Роль верификации не настроена. Обратитесь к администратору.",
                ephemeral=True,
            )
            log.warning("VERIFIED_ROLE_ID не задан в конфигурации")
            return

        verified_role = guild.get_role(settings.VERIFIED_ROLE_ID)
        if verified_role is None:
            await interaction.response.send_message(
                "Роль верификации не найдена на сервере. Обратитесь к администратору.",
                ephemeral=True,
            )
            log.warning("Роль с ID %s не найдена на сервере", settings.VERIFIED_ROLE_ID)
            return

        if verified_role in member.roles:
            await interaction.response.send_message(
                "Вы уже прошли верификацию ✅", ephemeral=True
            )
            return

        try:
            await member.add_roles(verified_role, reason="Верификация по кнопке")

            if settings.UNVERIFIED_ROLE_ID:
                unverified_role = guild.get_role(settings.UNVERIFIED_ROLE_ID)
                if unverified_role and unverified_role in member.roles:
                    await member.remove_roles(unverified_role, reason="Верификация по кнопке")

        except discord.Forbidden:
            await interaction.response.send_message(
                "У бота недостаточно прав, чтобы выдать роль. Обратитесь к администратору.",
                ephemeral=True,
            )
            log.error("Недостаточно прав для выдачи роли %s участнику %s", verified_role, member)
            return

        await interaction.response.send_message(
            "Вы успешно прошли верификацию! Добро пожаловать 🎉", ephemeral=True
        )

        await self._send_log(guild, member)

    async def _send_log(self, guild: discord.Guild, member: discord.Member):
        if not settings.VERIFICATION_LOG_CHANNEL_ID:
            return

        log_channel = guild.get_channel(settings.VERIFICATION_LOG_CHANNEL_ID)
        if log_channel is None:
            log.warning("Канал логов верификации %s не найден", settings.VERIFICATION_LOG_CHANNEL_ID)
            return

        embed = discord.Embed(
            description=f"🤍 {member.mention} прошёл верификацию",
            color=discord.Color(0x808080),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Пользователь", value=f"{member.mention} (`{member.id}`)", inline=False)

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Не удалось отправить лог верификации в канал %s", log_channel.id)


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(VerificationView())
        self._panel_posted = False

    @commands.Cog.listener()
    async def on_ready(self):
        # публикуем панель верификации один раз за жизнь процесса
        # (то есть при каждом старте/редеплое бота — заново)
        if self._panel_posted:
            return
        self._panel_posted = True

        for guild in self.bot.guilds:
            channel = guild.get_channel(settings.VERIFICATION_CHANNEL_ID)
            if channel is None:
                continue

            # чистим старые сообщения бота в этом канале, чтобы не копились панели
            try:
                await channel.purge(limit=50, check=lambda m: m.author == self.bot.user)
            except discord.Forbidden:
                log.warning("Нет прав на очистку канала верификации %s", channel.id)
            except discord.HTTPException:
                log.exception("Не удалось очистить канал верификации %s", channel.id)

            embed = discord.Embed(
                title=settings.VERIFICATION_TITLE,
                description=settings.VERIFICATION_DESCRIPTION,
                color=discord.Color(0x808080),
            )
            embed.set_image(url=settings.VERIFICATION_IMAGE_URL)
            view = VerificationView()

            try:
                await channel.send(embed=embed, view=view)
                log.info("Панель верификации опубликована в канале %s", channel.id)
            except discord.HTTPException:
                log.exception("Не удалось опубликовать панель верификации в канале %s", channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
