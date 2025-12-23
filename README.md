# Sentry Security Bot

Sentry Security Bot is a modular, admin-focused Telegram group management bot designed to help moderators manage large communities efficiently.  
It provides tools for moderation, automation, anti-spam, user management, and customization.

This project is a modernized and restructured version of a classic Telegram moderation bot, refactored for better maintainability and cloud deployment.

---

## ✨ Features

### 🛡️ Moderation
- Ban / Unban / Kick users
- Mute / Unmute users
- Warn system with limits and actions
- Global bans (GBan) support

### 🔒 Group Controls
- Lock and unlock content types (media, links, stickers, etc.)
- Anti-flood protection
- Custom filters and auto-responses

### 👋 Welcome System
- Custom welcome messages
- Enable / disable welcomes per chat
- Reset and manage welcome templates

### 📝 Notes
- Save, retrieve, list, and delete notes
- Supports text formatting and placeholders

### 🧑 User Utilities
- AFK system
- User info & bios
- Chat and user tracking (for admin use)

### ⚙️ Admin Tools
- Admin-only commands
- Connection system (manage groups remotely)
- Logging to admin channels

---

## 🧠 How It Works

- Built on **python-telegram-bot (legacy v11.x)** using long polling
- Uses **PostgreSQL** via **SQLAlchemy** for persistent storage
- Modular architecture:
  - Each feature lives in its own module
  - Modules are dynamically loaded at startup
- Designed to run on modern platforms like **Railway**, **Docker**, or **VPS**

---

## 🚀 Deployment

### Requirements
- Python **3.8.x** (recommended)
- PostgreSQL database
- Telegram Bot Token

### Environment Variables

You **must** set the following environment variables:

| Variable | Description | Example |
|--------|------------|---------|
| `TOKEN` | Telegram bot token | `123456:ABC-DEF...` |
| `DB_URI` | PostgreSQL connection string | `postgresql://user:pass@host:5432/dbname` |
| `OWNER_ID` | Telegram user ID of bot owner | `123456789` |
| `WORKERS` | Number of worker threads | `8` |
| `ENV` | Runtime mode | `production` |

Optional:
- `LOG_CHANNEL`
- `SUDO_USERS`
- `WEBHOOK_URL` (if using webhooks)

---

## ▶️ Running the Bot

```bash
python -m utils

## 🚀 Deployment

### Requirements
- Python **3.8.x** (recommended)
- PostgreSQL database
- Telegram Bot Token

### Environment Variables

You **must** set the following environment variables:

| Variable | Description | Example |
|--------|------------|---------|
| `TOKEN` | Telegram bot token | `123456:ABC-DEF...` |
| `DB_URI` | PostgreSQL connection string | `postgresql://user:pass@host:5432/dbname` |
| `OWNER_ID` | Telegram user ID of bot owner | `123456789` |
| `WORKERS` | Number of worker threads | `8` |
| `ENV` | Runtime mode | `production` |

Optional:
- `LOG_CHANNEL`
- `SUDO_USERS`
- `WEBHOOK_URL` (if using webhooks)

---

## ▶️ Running the Bot

```bash
python -m utils
