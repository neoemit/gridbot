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

from __future__ import annotations
import re
from pathlib import Path
from typing import Iterable

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import ContextTypes

from .config import AUTHORIZED_USERS, EXCEL_FOLDER
from .state import set_state, get_state, clear_state
from .excel import list_excel_files, list_sheets, read_cell
from .database import (
    get_favourites,
    get_favourite_by_id,
    add_favourite,
    favourite_exists,
)

# ---------- UI helpers ----------

def _exit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Exit", callback_data="exit")]])

def _menu_kb(has_favs: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("📂 Select from Excel files", callback_data="menu:files")]
    ]
    if has_favs:
        rows.append([InlineKeyboardButton("⭐ Select from favourites", callback_data="menu:favs")])
    rows.append([InlineKeyboardButton("❌ Exit", callback_data="exit")])
    return InlineKeyboardMarkup(rows)

def _list_kb(prefix: str, labels: list[str]) -> InlineKeyboardMarkup:
    """Create a single-column keyboard with an Exit row at the end."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(label, callback_data=f"{prefix}:{i}")]
        for i, label in enumerate(labels)
    ]
    rows.append([InlineKeyboardButton("❌ Exit", callback_data="exit")])
    return InlineKeyboardMarkup(rows)

# ---------- Auth ----------

async def _check_auth(update: Update) -> bool:
    uid = update.effective_user.id
    if AUTHORIZED_USERS and uid not in AUTHORIZED_USERS:
        if update.message:
            await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        elif update.callback_query:
            await update.callback_query.answer("Not authorized", show_alert=True)
        return False
    return True

# ---------- Entry / Exit ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    uid = update.effective_user.id
    set_state(uid, "main_menu")
    favs = get_favourites(uid)
    text = "Choose an option:"
    kb = _menu_kb(has_favs=bool(favs))
    if update.message:
        await update.message.reply_text(text, reply_markup=kb)
    else:
        # In case someone calls /start via a button—rare, but safe
        await update.callback_query.edit_message_text(text, reply_markup=kb)

async def exit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update):
        return
    uid = update.effective_user.id
    clear_state(uid)
    msg = "Exited. Type /start to begin again."
    if update.message:
        await update.message.reply_text(msg)
    else:
        await update.callback_query.edit_message_text(msg)

# ---------- Callback router ----------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Single router for all callback buttons."""
    if not await _check_auth(update):
        return
    q = update.callback_query
    uid = update.effective_user.id
    await q.answer()

    data = q.data or ""

    if data == "exit":
        clear_state(uid)
        await q.edit_message_text("Exited. Type /start to begin again.")
        return

    # Main menu selections
    if data == "menu:files":
        files = list_excel_files(EXCEL_FOLDER)
        if not files:
            await q.edit_message_text("No Excel files found in the configured folder.", reply_markup=_exit_kb())
            set_state(uid, "main_menu")
            return
        # store list in state to avoid long callback_data
        set_state(uid, "choose_file", files=files)
        await q.edit_message_text(
            "Select a file:",
            reply_markup=_list_kb("file", [p.name for p in files])
        )
        return

    if data == "menu:favs":
        favs = get_favourites(uid)
        if not favs:
            await q.edit_message_text("No favourites saved yet.", reply_markup=_menu_kb(False))
            set_state(uid, "main_menu")
            return
        # show by nickname, carry DB id in callback
        set_state(uid, "choose_fav")
        rows = [
            [InlineKeyboardButton(nickname, callback_data=f"fav:{fav_id}")]
            for (fav_id, nickname, _fp, _sh, _cell) in favs
        ]
        rows.append([InlineKeyboardButton("❌ Exit", callback_data="exit")])
        await q.edit_message_text("Select a favourite:", reply_markup=InlineKeyboardMarkup(rows))
        return

    # File chosen
    if data.startswith("file:"):
        st = get_state(uid) or {}
        files: list[Path] = st.get("files", [])
        try:
            idx = int(data.split(":", 1)[1])
            file_path = files[idx]
        except Exception:  # noqa: BLE001
            await q.edit_message_text("Invalid file selection.", reply_markup=_exit_kb())
            return

        sheets = list_sheets(file_path)
        set_state(uid, "choose_sheet", file=file_path, sheets=sheets)
        await q.edit_message_text(
            f"Select a sheet from *{file_path.name}*:",
            reply_markup=_list_kb("sheet", sheets),
            parse_mode="Markdown"
        )
        return

    # Sheet chosen
    if data.startswith("sheet:"):
        st = get_state(uid) or {}
        sheets: list[str] = st.get("sheets", [])
        try:
            idx = int(data.split(":", 1)[1])
            chosen_sheet = sheets[idx]
        except Exception:  # noqa: BLE001
            await q.edit_message_text("Invalid sheet selection.", reply_markup=_exit_kb())
            return

        set_state(uid, "choose_cell", sheet=chosen_sheet, file=st.get("file"))
        await q.edit_message_text(
            "Enter cell coordinate (e.g. C3):",
            reply_markup=_exit_kb()
        )
        return

    # Favourite chosen by ID
    if data.startswith("fav:"):
        try:
            fav_id = int(data.split(":", 1)[1])
        except ValueError:
            await q.edit_message_text("Invalid favourite selection.", reply_markup=_exit_kb())
            return

        fav = get_favourite_by_id(fav_id)
        if not fav:
            await q.edit_message_text("Favourite not found.", reply_markup=_exit_kb())
            return

        _id, nickname, file_path, sheet_name, cell_coord = fav
        value = read_cell(Path(file_path), sheet_name, cell_coord)
        await q.edit_message_text(f"Value for *{nickname}* ({sheet_name}!{cell_coord}): {value}", parse_mode="Markdown")
        # Back to main menu
        favs = get_favourites(uid)
        await q.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs)))
        set_state(uid, "main_menu")
        return

    # Unknown callback
    await q.edit_message_text("Sorry, I didn’t understand that action.", reply_markup=_exit_kb())

# ---------- Text messages ----------

_CELL_RE = re.compile(r"^[A-Za-z]+\d+$")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free text for cell coordinates or nickname."""
    if not await _check_auth(update):
        return
    uid = update.effective_user.id
    st = get_state(uid)

    # No state → show main menu on any text
    if not st:
        favs = get_favourites(uid)
        set_state(uid, "main_menu")
        await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs)))
        return

    step = st.get("step")

    # User typed /exit as text (in case they didn’t press the button)
    if update.message.text.strip().lower() == "/exit":
        await exit_cmd(update, context)
        return

    # Expecting a cell coordinate
    if step == "choose_cell":
        coord = update.message.text.strip()
        if not _CELL_RE.match(coord):
            await update.message.reply_text("Invalid cell format. Please enter like C3.", reply_markup=_exit_kb())
            return

        file_path: Path = st["file"]
        sheet_name: str = st["sheet"]
        value = read_cell(file_path, sheet_name, coord)
        await update.message.reply_text(f"Value in {sheet_name}!{coord}: {value}")

        # Ask to save favourite if not already there
        if not favourite_exists(uid, str(file_path), sheet_name, coord):
            set_state(uid, "ask_nickname", file=file_path, sheet=sheet_name, cell=coord)
            await update.message.reply_text(
                "Do you want to save this as a favourite? If yes, type a nickname. If not, press ❌ Exit or /exit.",
                reply_markup=_exit_kb()
            )
        else:
            # Back to main menu
            favs = get_favourites(uid)
            set_state(uid, "main_menu")
            await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs)))
        return

    # Expecting a nickname for favourite
    if step == "ask_nickname":
        nickname = update.message.text.strip()
        file_path: Path = st["file"]
        sheet_name: str = st["sheet"]
        cell: str = st["cell"]
        add_favourite(uid, nickname, str(file_path), sheet_name, cell)
        await update.message.reply_text(f"Favourite “{nickname}” saved ✅")
        favs = get_favourites(uid)
        set_state(uid, "main_menu")
        await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs)))
        return

    # Fallback: show menu
    favs = get_favourites(uid)
    set_state(uid, "main_menu")
    await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs)))
