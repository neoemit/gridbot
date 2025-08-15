# 📊 GridBot  

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-yellow.svg)](https://opensource.org/license/gpl-3-0)

A Telegram bot that lets you:  
- Browse and select Excel files from a configured folder  
- Read specific cells or values (including formulas when possible)  
- Save frequently used cells as **favourites** for quick access  
- Restrict usage to authorized users only  

## 🚀 Features
- Supports both `.xlsx` and `.xls` files  
- Formula evaluation for `.xlsx` using [`xlcalculator`](https://pypi.org/project/xlcalculator/)  
- Favourites saved in a local SQLite database (`favourites.db`)  
- User-specific favourites (isolated per Telegram user)  
- Authorization system (`AUTHORIZED_USERS` list in `.env`)  
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
```

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
  - ❌ Exit  
- Follow the guided flow to pick a file → sheet → cell.  
- You can save a cell to favourites for quicker future access.  
- At any step, use `/exit` to stop.  
- If you’re not in the authorized user list, the bot replies with:  
  ```
  Sorry, you are not authorized to use this bot.
  ```

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
```

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
