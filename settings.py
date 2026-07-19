"""
Конфигурация бота. Все значения берутся из переменных окружения.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _int_set_env(name: str, default: set[int]) -> set[int]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return {int(v.strip()) for v in value.split(",") if v.strip()}


# --- основное ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# --- каналы ---
WELCOME_CHANNEL_ID = _int_env("WELCOME_CHANNEL_ID", 1527984319509823549)
VERIFICATION_CHANNEL_ID = _int_env("VERIFICATION_CHANNEL_ID", 1527984945220550697)

# --- роли ---
VERIFIED_ROLE_ID = _int_env("VERIFIED_ROLE_ID", 0)
UNVERIFIED_ROLE_ID = _int_env("UNVERIFIED_ROLE_ID", 0)

# Роль, которая выдаётся автоматически всем новым участникам при входе
JOIN_ROLE_ID = _int_env("JOIN_ROLE_ID", 1528014100066603159)

# Канал, куда пишутся логи о прохождении верификации
VERIFICATION_LOG_CHANNEL_ID = _int_env("VERIFICATION_LOG_CHANNEL_ID", 1528009513213493320)

# --- тексты верификации ---
VERIFICATION_TITLE = os.getenv("VERIFICATION_TITLE", "Верификация")
VERIFICATION_DESCRIPTION = os.getenv(
    "VERIFICATION_DESCRIPTION",
    "Нажмите на кнопку ниже, чтобы подтвердить, что вы не бот, и получить доступ к серверу.",
)
VERIFICATION_BUTTON_LABEL = os.getenv("VERIFICATION_BUTTON_LABEL", "Верифицироваться")
VERIFICATION_IMAGE_URL = os.getenv(
    "VERIFICATION_IMAGE_URL", "https://i.postimg.cc/T2mLYLtV/image.png"
)

# --- логи приглашений ---
INVITE_LOG_CHANNEL_ID = _int_env("INVITE_LOG_CHANNEL_ID", 1528009997286510703)

# --- модерация ---
BAN_LOG_CHANNEL_ID = _int_env("BAN_LOG_CHANNEL_ID", 1528009214138646649)
MUTE_LOG_CHANNEL_ID = _int_env("MUTE_LOG_CHANNEL_ID", 1528218178759561276)

# Роли, которым разрешено использовать /ban /kick /mute /unban /unmute /server
STAFF_ROLE_IDS = _int_set_env(
    "STAFF_ROLE_IDS",
    {
        1527719775114105073,
        1527719636420919396,
        1527719311970668716,
        1527718985485910016,
    },
)

# Роли, которым разрешено использовать /profile
PROFILE_ROLE_IDS = _int_set_env(
    "PROFILE_ROLE_IDS",
    {
        1528013970823184555,
    },
)
