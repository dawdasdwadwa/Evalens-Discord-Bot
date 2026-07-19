"""
Ког верификации участников по кнопке.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import settings

log = logging.getLogger("wildsync.verification")

VERIFY_BUTTON_CUSTOM_ID = "wildsync:verify_button"


class VerificationView(discord.ui.View):
    """Постоянная View с кнопкой верификации."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label=settings.VERIFICATION_BUTTON_LABEL,
        style=discord.ButtonStyle.success,
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


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(VerificationView())

    @app_commands.command(
        name="setup_verification",
        description="Опубликовать панель верификации в текущем канале (только для администраторов).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verification(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=settings.VERIFICATION_TITLE,
            description=settings.VERIFICATION_DESCRIPTION,
            color=discord.Color(0x96C4C4),
        )
        view = VerificationView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("Панель верификации опубликована ✅", ephemeral=True)

    @setup_verification.error
    async def setup_verification_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Эта команда доступна только администраторам.", ephemeral=True
            )
        else:
            log.exception("Ошибка команды setup_verification", exc_info=error)
            await interaction.response.send_message("Произошла ошибка при выполнении команды.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
