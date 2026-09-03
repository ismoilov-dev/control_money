# Personal expense & income tracker (Telegram)

Single-user Telegram bot for simple weekly budget tracking.

## Features

- Fast natural-language expense tracking (`-12 taksi`, `-150 ovqat`, `30 taksi`)
- Automatic shorthand scaling (`12 taksi` -> 12 000 so'm, `150 ovqat` -> 150 000 so'm)
- Income logging (`+3000000 maosh`)
- Real-time weekly balance feedback on every expense
- `/set_weekly_money 300k` to set weekly spending budget
- `/today`, `/week`, `/month` reports

## Setup

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

Run locally:

```bash
python3 main.py
```

## Commands

| Command | Description |
| --- | --- |
| `/start` | Bot instruction manual |
| `/set_weekly_money 300k` | Set weekly spending budget |
| `/today` | Today's expenses & income |
| `/week` | This week's total report & remaining budget |
| `/month` | Monthly summary |
