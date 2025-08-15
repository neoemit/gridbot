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

import sqlite3
from typing import Any, Iterable
from .config import DB_PATH

def init_db() -> None:
    """Create tables if they don’t exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS favourites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nickname TEXT NOT NULL,
            file_path TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            cell_coord TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def _run(query: str, params: Iterable[Any] = (), *, one: bool = False, all_: bool = False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    result = None
    if one:
        result = c.fetchone()
    elif all_:
        result = c.fetchall()
    conn.commit()
    conn.close()
    return result

def get_favourites(user_id: int) -> list[tuple]:
    return _run(
        "SELECT id, nickname, file_path, sheet_name, cell_coord FROM favourites WHERE user_id=?",
        (user_id,),
        all_=True
    ) or []

def get_favourite_by_id(fav_id: int) -> tuple | None:
    return _run(
        "SELECT id, nickname, file_path, sheet_name, cell_coord FROM favourites WHERE id=?",
        (fav_id,),
        one=True
    )

def add_favourite(user_id: int, nickname: str, file_path: str, sheet_name: str, cell_coord: str) -> None:
    _run(
        "INSERT INTO favourites (user_id, nickname, file_path, sheet_name, cell_coord) VALUES (?, ?, ?, ?, ?)",
        (user_id, nickname, file_path, sheet_name, cell_coord)
    )

def favourite_exists(user_id: int, file_path: str, sheet_name: str, cell_coord: str) -> bool:
    row = _run(
        "SELECT id FROM favourites WHERE user_id=? AND file_path=? AND sheet_name=? AND cell_coord=?",
        (user_id, file_path, sheet_name, cell_coord),
        one=True
    )
    return row is not None
