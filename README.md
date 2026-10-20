# 📊 GridBot  

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-yellow.svg)](https://opensource.org/license/gpl-3-0)

A Telegram bot that lets you:  
- Browse and select Excel files from a configured folder  
- Read specific cells or values (including formulas when possible)  
- Save frequently used cells as **favourites** for quick access  
- Rename, re-point, delete and **share favourites** with other users  
- Restrict usage to approved users, with access requests reviewed by an admin in Telegram  

## 🚀 Features
- Supports both `.xlsx` and `.xls` files  
- Formula evaluation for `.xlsx` using [`xlcalculator`](https://pypi.org/project/xlcalculator/)  
- Favourites saved in a local SQLite database (`favourites.db`)  
- User-specific favourites (isolated per Telegram user)  
- Authorization system: `AUTHORIZED_USERS` in `.env` merged with users the admin approved  
- Modular codebase for easy maintenance  
- Hidden files (starting with `.`) are ignored  
- Telegram inline buttons instead of numeric replies  
- `/exit` command available at every step to quit the flow  

## 📂 Project Structure
```
gridbot/
│── __init__.py
│── main.py           # Entry point
│── config.py         # Config & environment
│── database.py       # SQLite database
│── excel.py          # Excel file utilities
│── state.py          # User state management
│── handlers.py       # Telegram bot handlers
│── requirements.txt  # Dependencies
│── README.md         # This file
```

## 🔧 Installation

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/gridbot.git
cd gridbot
```

### 2. Create a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate   # On macOS/Linux
.venv\Scripts\activate      # On Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

## ⚙️ Configuration

### 1. Create a .env file in the project root:
```ini
# Telegram Bot Token
TOKEN=123456789:ABC-YourBotTokenHere

# Path to folder with Excel files
EXCEL_FOLDER=/path/to/spreadsheet/folder

# Path to SQLite database
DB_PATH=favourites.db

# Comma-separated list of authorized Telegram user IDs
AUTHORIZED_USERS=123456789,987654321

# Telegram user ID of the admin who approves or denies access requests
ADMIN_USER_ID=123456789
```

The admin must have started a chat with the bot so it can send them access requests.

### 2. Place your Excel files

Put all `.xls` and `.xlsx` files you want to access inside the folder you set in `EXCEL_FOLDER`.  
👉 Hidden files (those starting with `.`) will be ignored automatically.

## ▶️ Usage

### Run the bot
```bash
# As a module
python -m gridbot.main

# Or directly
python gridbot/main.py
```

### Bot Interaction

- Send any message → The bot will prompt you with **buttons**:
  - 📂 Select from Excel files  
  - ⭐ Select from favourites (if any saved)  
  - ⚙️ Manage favourites (if any saved)  
  - ❌ Exit  
- Follow the guided flow to pick a file → sheet → cell.  
- You can save a cell to favourites for quicker future access.  
- **Manage favourites** lets you rename a favourite, change its file/sheet/cell, delete it, or share it.  
- **Sharing**: pick another user and they get a message with **Accept** / **Deny** buttons. If they accept, the favourite is copied into their favourites; either way, you’re notified.  
  Only approved users who have messaged the bot at least once can be picked.  
- At any step, use `/exit` to stop.  

### Access approval

A user can use the bot if they are the admin (`ADMIN_USER_ID`), are listed in `AUTHORIZED_USERS`, or were approved by the admin.

- When anyone else messages the bot, it sends the admin an **access request** with the user’s name, profile link, @username, ID, language and Premium status, plus **Approve** / **Deny** buttons. The user is told their request is waiting.
- **Approved**: the user is notified and can start using the bot.
- **Denied**: the user is notified and further attempts are **not** sent to the admin again. They can only get in if they are added manually, either to `AUTHORIZED_USERS` or by setting their `status` to `approved` in the `users` table.
- Without `ADMIN_USER_ID`, no requests are sent and only already approved users can use the bot.
- Removing someone from `AUTHORIZED_USERS` revokes their access unless the admin also approved them.

## 🗄️ Database

Favourites are stored in a simple SQLite database (`favourites.db`).

Schema:
```sql
CREATE TABLE IF NOT EXISTS favourites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    nickname TEXT NOT NULL,
    file_path TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    cell_coord TEXT NOT NULL
);

-- Users who have interacted with the bot (share targets) and their access request
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    username TEXT,
    language_code TEXT,
    is_premium INTEGER,
    status TEXT,           -- NULL (no request) | 'pending' | 'approved' | 'denied'
    requested_at TEXT,     -- UTC
    decided_at TEXT        -- UTC
);

-- Pending share requests (deleted once accepted or denied)
CREATE TABLE IF NOT EXISTS share_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    nickname TEXT NOT NULL,
    file_path TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    cell_coord TEXT NOT NULL
);
```

New tables are created automatically on startup; existing favourites are untouched.

## 📦 Dependencies

Main libraries:
- `python-telegram-bot`
- `python-dotenv`
- `openpyxl`
- `xlrd`
- `xlcalculator`

Install via:
```bash
pip install -r requirements.txt
```

## 🛠 Development Notes

- Works on Python 3.9+  
- Ensure Excel files are **not password protected**  
- Formula evaluation via `xlcalculator` may not support 100% of Excel’s formulas  

## 📝 License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
