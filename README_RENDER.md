# Telegram File Host Bot — Production Render setup

## What this version does
- Upload a `.py` file to the Telegram bot.
- Detects imported third-party libraries and installs them automatically in the persistent runner venv.
- Verifies dependencies before launch.
- Automatically hosts a safe-reviewed upload immediately when `AUTO_HOST_ON_UPLOAD=1`.
- Resolves an uploaded Telegram bot's `@username` when a literal bot token is present in the uploaded source.
- Stores uploaded files, bot state, logs, and the runner virtual environment on `/var/data`.
- Uses atomic state writes plus a backup file.
- Watchdog restarts approved processes that unexpectedly stop.
- Keeps risky/suspicious uploads behind the existing admin safety gate instead of executing them automatically.

## Render
Create a **Web Service / Blueprint** from this repository. `render.yaml` configures the service.

Required environment variables:
- `BOT_TOKEN`: the hosting/admin bot token from BotFather
- `ADMIN_ID`: your numeric Telegram user ID
- `MINI_APP_URL`: optional; your deployed Mini App URL

Already configured by `render.yaml`:
- `STORAGE_DIR=/var/data`
- `AUTO_INSTALL_PACKAGES=1`
- `AUTO_HOST_ON_UPLOAD=1`
- persistent disk mounted at `/var/data`

## Important persistence note
Persistent disk protects files/data across service restarts and redeploys. It does not make a broken uploaded program immortal: if an uploaded bot exits, the watchdog attempts to restart it. The platform itself can still have outages, so no hosting service can honestly guarantee zero downtime.

## Telegram bot username
For instant `@username`, the uploaded script should contain its Telegram token as a literal assignment such as:

`BOT_TOKEN = "123456:ABC..."`

The host uses Telegram `getMe` only to resolve the username and never sends the token in the chat message. If the token is only fetched dynamically from an external secret manager/environment, username resolution may not be possible from the uploaded source.

## One production instance
Run only one copy of this hosting bot with the same `BOT_TOKEN`. Do not also run the same bot on Replit, Termux, Pydroid, another Render service, or your PC at the same time, otherwise Telegram polling conflicts can occur.
