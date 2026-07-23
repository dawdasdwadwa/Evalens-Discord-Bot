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

# Папка для файлов, которые должны переживать редеплой (temp_bans.json,
# ticket_history.json). На Railway сюда монтируется Volume (Mount Path),
# см. переменную DATA_DIR в Railway Variables. По умолчанию — текущая
# рабочая директория (как было раньше, без persistence).
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

# --- каналы ---
WELCOME_CHANNEL_ID = _int_env("WELCOME_CHANNEL_ID", 1451962767614673019)
VERIFICATION_CHANNEL_ID = _int_env("VERIFICATION_CHANNEL_ID", 1397851165407842307)

# --- роли ---
VERIFIED_ROLE_ID = _int_env("VERIFIED_ROLE_ID", 1397851164279701547)
UNVERIFIED_ROLE_ID = _int_env("UNVERIFIED_ROLE_ID", 1502733657645908199)

# Роль, которая выдаётся автоматически всем новым участникам при входе
JOIN_ROLE_ID = _int_env("JOIN_ROLE_ID", 1502733657645908199)

# Канал, куда пишутся логи о прохождении верификации
VERIFICATION_LOG_CHANNEL_ID = _int_env("VERIFICATION_LOG_CHANNEL_ID", 1529707489635864586)

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
INVITE_LOG_CHANNEL_ID = _int_env("INVITE_LOG_CHANNEL_ID", 1529708431219495003)

# --- модерация ---
BAN_LOG_CHANNEL_ID = _int_env("BAN_LOG_CHANNEL_ID", 1529707400435859538)
MUTE_LOG_CHANNEL_ID = _int_env("MUTE_LOG_CHANNEL_ID", 1529707327387730000)

# Роли, которым разрешено использовать /ban /kick /mute /unban /unmute /server
# (общий стафф — на новом сервере также имеет доступ к тикетам «Жалоба на игрока»)
STAFF_ROLE_IDS = _int_set_env(
    "STAFF_ROLE_IDS",
    {
        1494820871821459517,
    },
)

# Роли, которым разрешено использовать /profile
PROFILE_ROLE_IDS = _int_set_env(
    "PROFILE_ROLE_IDS",
    {
        1397851164279701547,
    },
)

# --- логи ролей ---
# Канал, куда логируются выдача/снятие ролей участникам, а также создание/удаление
# ролей на сервере. Требует у бота право "View Audit Log", иначе исполнитель
# действия в логе будет отмечен как "не удалось определить".
ROLE_LOG_CHANNEL_ID = _int_env("ROLE_LOG_CHANNEL_ID", 1529707155694026762)

# --- тикеты ---
# Канал, где публикуется панель с кнопками для создания тикетов
TICKETS_CHANNEL_ID = _int_env("TICKETS_CHANNEL_ID", 1529709927302434946)

# Канал, куда логируются открытие/закрытие тикетов
TICKET_LOG_CHANNEL_ID = _int_env("TICKET_LOG_CHANNEL_ID", 1529707444220203178)

# Категории для тикетов «Жалоба на игрока»
PLAYER_REPORT_OPEN_CATEGORY_ID = _int_env("PLAYER_REPORT_OPEN_CATEGORY_ID", 1529710584717643877)
PLAYER_REPORT_CLOSED_CATEGORY_ID = _int_env("PLAYER_REPORT_CLOSED_CATEGORY_ID", 1529710630200938617)

# Категории для тикетов «Жалоба на персонал»
STAFF_REPORT_OPEN_CATEGORY_ID = _int_env("STAFF_REPORT_OPEN_CATEGORY_ID", 1529710741232291860)
STAFF_REPORT_CLOSED_CATEGORY_ID = _int_env("STAFF_REPORT_CLOSED_CATEGORY_ID", 1529710798690058390)

# Роли, у которых ЕСТЬ ДОСТУП к тикетам «Жалоба на персонал» (видят канал,
# могут «Рассмотреть» / «Закрыть» / «Добавить пользователя») — сюда НЕ входит
# весь STAFF_ROLE_IDS, только эти две роли. Они же пингуются при создании такого тикета.
STAFF_REPORT_ACCESS_ROLE_IDS = _int_set_env(
    "STAFF_REPORT_ACCESS_ROLE_IDS",
    {
        1397851164292415509,
        1397851164292415508,
    },
)

# Роли, которые пингуются при создании тикета «Жалоба на персонал»
STAFF_REPORT_PING_ROLE_IDS = _int_set_env(
    "STAFF_REPORT_PING_ROLE_IDS",
    STAFF_REPORT_ACCESS_ROLE_IDS,
)

# Роли, у которых есть доступ к тикету «Жалоба на игрока» (входят в STAFF_ROLE_IDS),
# но которых не нужно пинговать при его создании. Пусто — значит пингуются все.
TICKET_NO_PING_ROLE_IDS = _int_set_env(
    "TICKET_NO_PING_ROLE_IDS",
    set(),
)

# Роли, которым закрывается доступ к каналу тикета после его закрытия
# (наравне с автором тикета). Пусто — значит доступ теряет только автор тикета,
# весь стафф по-прежнему видит закрытые тикеты.
TICKET_CLOSED_HIDDEN_ROLE_IDS = _int_set_env(
    "TICKET_CLOSED_HIDDEN_ROLE_IDS",
    set(),
)

# Роли, которым разрешено НАВСЕГДА УДАЛЯТЬ тикеты (кнопка «Удалить тикет»).
# Это отдельное, более узкое право, чем общий доступ к тикету — действует
# на тикеты ЛЮБОГО типа (и «Жалоба на игрока», и «Жалоба на персонал»).
TICKET_DELETE_ROLE_IDS = _int_set_env(
    "TICKET_DELETE_ROLE_IDS",
    {
        1397851164292415509,
        1397851164292415508,
    },
)

# Максимум тикетов, которые один участник может создать за 24 часа
TICKET_DAILY_LIMIT = _int_env("TICKET_DAILY_LIMIT", 10)
