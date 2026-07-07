# Pipeline: Telegram & WhatsApp UBT Automation Suite

Этот проект объединяет инструменты автоматизации трафика (UBT) для Telegram и WhatsApp, а также сервис уникализации медиафайлов.

## Архитектура проекта

Проект разделен на два основных компонента:

1. **uniqreo** — Telegram-бот для уникализации фото- и видеоматериалов (на базе Pillow и FFmpeg).
2. **ubtbot** — Набор сервисов для распределения и дожима трафика:
   - Telegram Redirect Bot — перенаправление пользователей на смартлинк с отслеживанием по Telegram ID.
   - WhatsApp Redirect Bot — аналогичный функционал для WhatsApp на базе Green-API.
   - S2S FastAPI Server — прием постбэков от партнерских программ (например, iMonetizeIt) и отправка уведомлений о конверсиях в Telegram.

## Структура директорий

```
pipeline/
├── docker-compose.yml       # Конфигурация для запуска всей экосистемы в Docker
├── requirements.txt         # Консолидированные зависимости проекта
├── .env.example             # Шаблон конфигурации окружения
├── .gitignore               # Исключения для Git
├── uniqreo/                 # Компонент уникализации медиа
│   ├── bot.py               # Бот уникализации
│   ├── Dockerfile           # Сборка контейнера с установкой FFmpeg
│   ├── requirements.txt     # Локальные зависимости uniqreo
│   └── core/                # Логика обработки изображений и видео
│       ├── config.py
│       ├── photo_processor.py
│       └── video_processor.py
└── ubtbot/                  # Компонент распределения трафика
    ├── bot.py               # Telegram редирект-бот
    ├── wa_bot.py            # WhatsApp редирект-бот (Green-API)
    ├── s2s_server.py        # FastAPI сервер для S2S-постбэков
    ├── requirements.txt     # Локальные зависимости ubtbot
    └── Dockerfile           # Сборка контейнера ubtbot
```

## Конфигурация окружения (.env)

Перед запуском скопируйте шаблон `.env.example` в файл `.env` и заполните параметры:

```bash
cp .env.example .env
```

### Основные параметры:
* **API_ID** и **API_HASH**: Данные приложения Telegram, полученные на https://my.telegram.org. Исползуются обоими Telegram-ботами.
* **BOT_TOKEN**: Токен Telegram-бота для уникализации медиа (uniqreo).
* **SOURCE_THREAD_ID** и **TARGET_THREAD_ID**: ID топиков/чатов для пересылки медиафайлов на уникализацию.
* **REDIRECT_BOT_TOKEN**: Токен Telegram-бота для перенаправления трафика.
* **SMARTLINK_URL**: Базовая ссылка (смартлинк) для перенаправления.
* **LEAD_CHAT_ID** и **LEAD_THREAD_ID**: Telegram Chat ID и Thread ID, куда S2S сервер будет отправлять уведомления о новых лидах.
* **GREEN_API_ID_INSTANCE** и **GREEN_API_TOKEN_INSTANCE**: Учетные данные инстанса Green-API для работы WhatsApp-бота.
* **GREEN_API_URL**: URL-адрес API Green-API (по умолчанию https://api.green-api.com).

## Развертывание и запуск

### Запуск через Docker Compose (Рекомендуется)

Все сервисы упакованы в Docker-контейнеры. Для сборки и запуска в фоновом режиме выполните:

```bash
docker-compose up --build -d
```

Команда запустит четыре контейнера:
1. `uniqreo_bot`
2. `tg_redirect_bot`
3. `wa_redirect_bot`
4. `s2s_fastapi` (доступен на порту 8000)

Для просмотра логов конкретного сервиса используйте:

```bash
docker-compose logs -f [service_name]
```

### Локальный запуск (без Docker)

1. Установите системные зависимости (для работы `uniqreo` требуется установленный в системе `ffmpeg`).
2. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Запуск сервисов по отдельности:
   * Бот уникализации:
     ```bash
     cd uniqreo && python bot.py
     ```
   * Telegram-бот редиректа:
     ```bash
     cd ubtbot && python bot.py
     ```
   * WhatsApp-бот редиректа:
     ```bash
     cd ubtbot && python wa_bot.py
     ```
   * S2S-сервер:
     ```bash
     cd ubtbot && uvicorn s2s_server:app --host 0.0.0.0 --port 8000
     ```

## Принципы работы дожим-воронки

1. При первом контакте пользователя с Telegram- или WhatsApp-ботом генерируется индивидуальная ссылка формата `{SMARTLINK_URL}{user_id}`, где `{user_id}` — это Telegram ID или номер телефона WhatsApp.
2. Бот отправляет приветственное сообщение с данной ссылкой.
3. В фоновом режиме запускается задача дожима:
   - Через 24 часа отправляется первое напоминание со ссылкой.
   - Через 48 часов отправляется финальное напоминание со ссылкой.
4. Отправка сообщений и логика дожима работают асинхронно и не блокируют прием новых сообщений.
