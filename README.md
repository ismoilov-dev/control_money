# Personal expense tracker (Telegram)

Single-user Telegram bot. Send a casual message (`30000 taksi`, `150k ovqatga ketdi`) and it logs the amount, guesses a category, and can show today / week / month totals.

## Features

- Natural-language logging (Uzbek / Russian / English keywords)
- Inline category picker when the category is unclear
- `/today`, `/week`, `/month` reports with category breakdown
- `/categories` to list, add, or delete categories
- `/delete_last` to undo a mistake
- Daily reminder at **21:00 Asia/Tashkent** if nothing was logged that day
- Ignores everyone except your Telegram user ID

## Setup

### 1. Create a bot token

1. Open Telegram and talk to [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, pick a name and username
3. Copy the token (looks like `123456789:AAH...`)

### 2. Get your numeric user ID

Message [@userinfobot](https://t.me/userinfobot) or [@getmyid_bot](https://t.me/getmyid_bot) and copy the number.

### 3. Install and configure

Python 3.11+ is recommended.

```bash
cd money
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
BOT_TOKEN=paste_token_here
ALLOWED_USER_ID=your_numeric_id
```

Optional:

```
DATABASE_PATH=data/expenses.db
TIMEZONE=Asia/Tashkent
```

### 4. Run locally

```bash
python main.py
```

Open Telegram, tap **Start** on your bot, then send something like `12000 taksi`.

SQLite data is stored in `data/expenses.db` (created automatically).

## Commands

| Command | What it does |
| --- | --- |
| `/start` | Short instructions |
| `/today` | Total + breakdown for today |
| `/week` | Monday–today |
| `/month` | This calendar month so far |
| `/categories` | Show categories; add or delete custom ones |
| `/delete_last` | Remove the most recent expense |

Amounts: `15000`, `15 000`, `150k` / `150к`, `2.5ming` all work. Category guessing uses keyword stems (`ovqatga` → Food, `taksi` → Transport).

## Deploy later

Keep **one** process running with long polling (this repo). Persist the SQLite file.

**Small VPS (systemd):** copy the project, create a venv, put `.env` next to `main.py`, run `python main.py` under systemd with `Restart=always`. Use a host timezone of `Asia/Tashkent` or set `TIMEZONE` in `.env`.

**Railway:** set `BOT_TOKEN` and `ALLOWED_USER_ID` as variables, start command `python main.py`, and attach a volume mounted at `/data` with `DATABASE_PATH=/data/expenses.db` so the database survives restarts.

Do not run two copies of the bot with the same token at once — Telegram only allows one polling connection.
