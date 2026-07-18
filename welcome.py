"""
Конфигурация бота. Все значения берутся из переменных окружения (.env).
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


# --- основное ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# --- каналы ---
WELCOME_CHANNEL_ID = _int_env("WELCOME_CHANNEL_ID", 1527984319509823549)
VERIFICATION_CHANNEL_ID = _int_env("VERIFICATION_CHANNEL_ID", 1527984945220550697)

# --- роли ---
# Роль, которая выдаётся после успешной верификации.
VERIFIED_ROLE_ID = _int_env("VERIFIED_ROLE_ID", 0)

# (опционально) роль, которая снимается после верификации,
# например "Незверифицирован" — если не используется, оставьте 0.
UNVERIFIED_ROLE_ID = _int_env("UNVERIFIED_ROLE_ID", 0)

# --- тексты верификации ---
VERIFICATION_TITLE = os.getenv("VERIFICATION_TITLE", "Верификация")
VERIFICATION_DESCRIPTION = os.getenv(
    "VERIFICATION_DESCRIPTION",
    "Нажмите на кнопку ниже, чтобы подтвердить, что вы не бот, и получить доступ к серверу.",
)
VERIFICATION_BUTTON_LABEL = os.getenv("VERIFICATION_BUTTON_LABEL", "✅ Верифицироваться")
