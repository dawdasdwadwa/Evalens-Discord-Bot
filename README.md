# Evalens Discord Bot — Приветствие и верификация

Discord-бот с двумя функциями:

1. **Приветствие** — при заходе нового участника генерируется картинка
   (аватар, ник, номер участника, название сервера) и отправляется
   в канал приветствия.
2. **Верификация по кнопке** — в канале верификации публикуется embed
   с кнопкой; при нажатии участнику выдаётся роль.

## Структура (плоская, все файлы в корне)

```
├── bot.py               # точка входа
├── settings.py          # чтение переменных окружения
├── welcome.py           # ког приветствия
├── verification.py      # ког верификации
├── image_generator.py   # генерация PNG-карточки (Pillow)
├── Poppins-*.ttf        # шрифты для карточки
├── requirements.txt
├── Procfile             # команда запуска для Railway
└── .env.example
```

## Установка

1. `pip install -r requirements.txt`
2. `cp .env.example .env` и заполнить:
   - `DISCORD_TOKEN` — токен бота
   - `WELCOME_CHANNEL_ID`, `VERIFICATION_CHANNEL_ID` — уже заполнены
   - `VERIFIED_ROLE_ID` — **обязательно**, ID роли после верификации
   - `UNVERIFIED_ROLE_ID` — опционально

## Права бота

Developer Portal → Bot → Privileged Gateway Intents:
- `SERVER MEMBERS INTENT` (обязательно)

Права на сервере (роль бота выше роли верификации):
- `Manage Roles`, `Send Messages`, `Embed Links`, `Attach Files`, `Use Application Commands`

## Запуск

```
python bot.py
```

## Деплой на Railway

1. Подключи репозиторий
2. Добавь переменные из `.env.example` в Variables (Railway → Settings → Variables)
3. Railway подхватит `requirements.txt` и `Procfile` (`worker: python bot.py`) автоматически

## Настройка верификации

После запуска один раз выполни в канале верификации:
```
/setup_verification
```
Кнопка постоянная — переживает перезапуски бота.
