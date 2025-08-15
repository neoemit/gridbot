# gridbot - A Telegram bot for spreadsheet lookups
# Copyright (C) 2025  Thomas La Mendola
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment from .env (if present)
load_dotenv()

# Telegram bot token
TOKEN: str | None = os.getenv("TOKEN")

# Folder containing Excel files
EXCEL_FOLDER: Path = Path(os.getenv("EXCEL_FOLDER", ".")).expanduser().resolve()

# SQLite DB path
DB_PATH: str = os.getenv("DB_PATH", "favourites.db")

# Comma-separated list of authorized Telegram user IDs
AUTHORIZED_USERS: list[int] = [
    int(u.strip())
    for u in os.getenv("AUTHORIZED_USERS", "").split(",")
    if u.strip()
]
