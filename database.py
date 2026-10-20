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
    # Everyone who has used the bot (share targets) and their access request, if any.
    # status: NULL (no request, e.g. listed in AUTHORIZED_USERS) | 'pending' | 'approved' | 'denied'
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            username TEXT,
            language_code TEXT,
            is_premium INTEGER,
            status TEXT,
            requested_at TEXT,
            decided_at TEXT
        )
    """)
    # Pending shares: a snapshot of the favourite, removed once accepted or denied
    c.execute("""
        CREATE TABLE IF NOT EXISTS share_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
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
    else:
        result = c.rowcount
    conn.commit()
    conn.close()
    return result

def get_favourites(user_id: int) -> list[tuple]:
    return _run(
        "SELECT id, nickname, file_path, sheet_name, cell_coord FROM favourites WHERE user_id=?",
        (user_id,),
        all_=True
    ) or []

def get_favourite_by_id(user_id: int, fav_id: int) -> tuple | None:
    return _run(
        "SELECT id, nickname, file_path, sheet_name, cell_coord FROM favourites WHERE id=? AND user_id=?",
        (fav_id, user_id),
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

def update_favourite_nickname(user_id: int, fav_id: int, nickname: str) -> bool:
    return _run(
        "UPDATE favourites SET nickname=? WHERE id=? AND user_id=?",
        (nickname, fav_id, user_id)
    ) > 0

def update_favourite_location(user_id: int, fav_id: int, file_path: str, sheet_name: str, cell_coord: str) -> bool:
    return _run(
        "UPDATE favourites SET file_path=?, sheet_name=?, cell_coord=? WHERE id=? AND user_id=?",
        (file_path, sheet_name, cell_coord, fav_id, user_id)
    ) > 0

def delete_favourite(user_id: int, fav_id: int) -> bool:
    return _run(
        "DELETE FROM favourites WHERE id=? AND user_id=?",
        (fav_id, user_id)
    ) > 0

# ---------- Users ----------

def upsert_user(user_id: int, full_name: str, username: str | None, language_code: str | None, is_premium: bool | None) -> None:
    """Create or refresh a user's profile. Never touches their access status."""
    _run(
        "INSERT INTO users (user_id, full_name, username, language_code, is_premium) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET full_name=excluded.full_name, username=excluded.username, "
        "language_code=excluded.language_code, is_premium=excluded.is_premium",
        (user_id, full_name, username, language_code, is_premium)
    )

def get_user(user_id: int) -> tuple | None:
    return _run(
        "SELECT user_id, full_name, username, status FROM users WHERE user_id=?",
        (user_id,),
        one=True
    )

def get_other_users(user_id: int) -> list[tuple]:
    return _run(
        "SELECT user_id, full_name, username, status FROM users WHERE user_id<>? ORDER BY full_name COLLATE NOCASE",
        (user_id,),
        all_=True
    ) or []

# ---------- Access requests ----------

def get_access_request(user_id: int) -> tuple | None:
    return _run(
        "SELECT user_id, full_name, username, language_code, is_premium, status, requested_at, decided_at "
        "FROM users WHERE user_id=?",
        (user_id,),
        one=True
    )

def set_access_pending(user_id: int) -> None:
    _run(
        "UPDATE users SET status='pending', requested_at=CURRENT_TIMESTAMP, decided_at=NULL WHERE user_id=?",
        (user_id,)
    )

def clear_access_request(user_id: int) -> None:
    _run(
        "UPDATE users SET status=NULL, requested_at=NULL, decided_at=NULL WHERE user_id=?",
        (user_id,)
    )

def set_user_status(user_id: int, status: str) -> bool:
    """Admin override of a user's access, whatever its current status."""
    return _run(
        "UPDATE users SET status=?, decided_at=CURRENT_TIMESTAMP WHERE user_id=?",
        (status, user_id)
    ) > 0

def decide_access_request(user_id: int, approved: bool) -> bool:
    """Approve or deny a pending request. False if it isn't pending (already decided or never requested)."""
    return _run(
        "UPDATE users SET status=?, decided_at=CURRENT_TIMESTAMP WHERE user_id=? AND status='pending'",
        ("approved" if approved else "denied", user_id)
    ) > 0

# ---------- Share requests ----------

def create_share_request(from_user_id: int, to_user_id: int, nickname: str, file_path: str, sheet_name: str, cell_coord: str) -> int:
    # Own connection: _run doesn't expose the new row id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO share_requests (from_user_id, to_user_id, nickname, file_path, sheet_name, cell_coord) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (from_user_id, to_user_id, nickname, file_path, sheet_name, cell_coord)
    )
    request_id = c.lastrowid
    conn.commit()
    conn.close()
    return request_id

def get_share_request(request_id: int, to_user_id: int) -> tuple | None:
    """Only returns the request if it is addressed to `to_user_id`."""
    return _run(
        "SELECT id, from_user_id, nickname, file_path, sheet_name, cell_coord FROM share_requests WHERE id=? AND to_user_id=?",
        (request_id, to_user_id),
        one=True
    )

def delete_share_request(request_id: int) -> bool:
    return _run(
        "DELETE FROM share_requests WHERE id=?",
        (request_id,)
    ) > 0
