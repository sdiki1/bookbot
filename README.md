# Book Sharing Bot + Admin Panel

Проект состоит из 2 сервисов:
- Telegram-бот для каталога и кнопки интереса;
- Веб-админка для удобного управления книгами через браузер.

## Что умеет

Пользователь в Telegram:
- `/start` — дисклеймер и меню;
- `/catalog` — карточки книг с фото и кнопкой `Хочу прочитать`;
- `/rules` — правила чтения и возврата.

Админ:
- в Telegram: `/addbook`, `/books`, `/setstatus`;
- в вебе: список книг, добавление, редактирование, быстрая смена статуса, удаление.

## Настройка `.env`

```bash
cp .env.example .env
```

Заполните:
- `BOT_TOKEN` — токен Telegram-бота.
- `BOT_ADMIN_ID` — ваш Telegram user id.
- `WEB_ADMIN_PASSWORD` — пароль для входа в веб-админку.

Остальное можно оставить по умолчанию:
- `BOOKBOT_DB_PATH=data/books.db`
- `BOOKBOT_UPLOAD_DIR=data/uploads`
- `WEB_ADMIN_USER=admin`
- `WEB_HOST=0.0.0.0`
- `WEB_PORT=8080`

## Локальный запуск (без Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Во второй вкладке терминала:

```bash
source .venv/bin/activate
python3 main_web.py
```

Админка будет доступна по адресу `http://localhost:8080`.
Вход: HTTP Basic (`WEB_ADMIN_USER` / `WEB_ADMIN_PASSWORD`).

## Запуск через Docker Compose

```bash
docker compose up -d --build
```

Сервисы:
- `bot` — Telegram-бот;
- `admin` — веб-админка на порту `WEB_PORT` (по умолчанию `8080`).

Остановка:

```bash
docker compose down
```
