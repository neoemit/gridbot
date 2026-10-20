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
import html
import re
from pathlib import Path
from typing import Iterable

from telegram import (
    Update,
    User,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .config import ADMIN_USER_ID, AUTHORIZED_USERS, EXCEL_FOLDER
from .state import set_state, get_state, clear_state
from .excel import list_excel_files, list_sheets, read_cell
from .database import (
    get_favourites,
    get_favourite_by_id,
    add_favourite,
    favourite_exists,
    update_favourite_nickname,
    update_favourite_location,
    delete_favourite,
    upsert_user,
    get_user,
    get_other_users,
    create_share_request,
    get_share_request,
    delete_share_request,
    get_access_request,
    set_access_pending,
    set_user_status,
    clear_access_request,
    decide_access_request,
)

# ---------- UI helpers ----------

def _exit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Exit", callback_data="exit")]])

def _menu_kb(has_favs: bool, uid: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("📂 Select from Excel files", callback_data="menu:files")]
    ]
    if has_favs:
        rows.append([InlineKeyboardButton("⭐ Select from favourites", callback_data="menu:favs")])
        rows.append([InlineKeyboardButton("⚙️ Manage favourites", callback_data="menu:manage")])
    if uid == ADMIN_USER_ID:
        rows.append([InlineKeyboardButton("👥 Manage users", callback_data="menu:users")])
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

def _back_exit_row(back_data: str) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton("⬅️ Back", callback_data=back_data),
        InlineKeyboardButton("❌ Exit", callback_data="exit"),
    ]

def _user_label(user: tuple) -> str:
    _uid, full_name, username, _status = user
    return f"{full_name} (@{username})" if username else full_name

def _fav_location(file_path: str, sheet_name: str, cell_coord: str) -> str:
    return f"📄 {Path(file_path).name} › {sheet_name}!{cell_coord}"

# ---------- Auth & access requests ----------

def _is_approved(user_id: int, status: str | None) -> bool:
    """Approved = the admin, listed in AUTHORIZED_USERS, or approved by the admin (stored in the DB)."""
    return user_id == ADMIN_USER_ID or user_id in AUTHORIZED_USERS or status == "approved"

def _profile_lines(req: tuple) -> list[str]:
    """HTML lines describing a user, from a get_access_request() row."""
    user_id, full_name, username, language_code, is_premium, _status, requested_at, _decided_at = req
    lines = [
        f'👤 <a href="tg://user?id={user_id}">{html.escape(full_name)}</a>',
        f"🔗 @{html.escape(username)}" if username else "🔗 No username",
        f"🆔 <code>{user_id}</code>",
        f"🌐 Language: {html.escape(language_code or 'unknown')}",
        f"⭐ Premium: {'yes' if is_premium else 'no'}",
    ]
    if requested_at:
        lines.append(f"🕒 Requested: {requested_at} UTC")
    return lines

def _decision_line(status: str | None, decided_at: str | None) -> str | None:
    if status == "approved":
        return f"✅ Approved {decided_at} UTC"
    if status == "denied":
        return f"❌ Denied {decided_at} UTC"
    return None

def _access_request_text(req: tuple) -> str:
    """HTML summary of an access request for the admin, including the decision once made."""
    lines = ["🔐 Access request", *_profile_lines(req)]
    decision = _decision_line(req[5], req[7])
    if decision:
        lines += ["", decision]
    return "\n".join(lines)

async def _request_access(user: User, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Record a pending request and send it to the admin. False if no admin is configured or reachable."""
    if ADMIN_USER_ID is None:
        return False
    set_access_pending(user.id)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"access_approve:{user.id}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"access_deny:{user.id}"),
    ]])
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=_access_request_text(get_access_request(user.id)),
            parse_mode="HTML",
            reply_markup=kb
        )
    except TelegramError as e:
        # Not left pending, so the user's next attempt retries (e.g. once the admin has started the bot)
        clear_access_request(user.id)
        print(f"⚠️ Couldn't send access request to admin {ADMIN_USER_ID}: {e}")
        return False
    return True

async def _check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    # Keep the user directory current: share targets, and the details shown to the admin
    upsert_user(user.id, user.full_name, user.username, user.language_code, user.is_premium)
    status = get_user(user.id)[3]
    if _is_approved(user.id, status):
        return True

    # Denied users are never re-sent to the admin; only a manual addition lets them in
    if status == "pending":
        msg = "Your access request is waiting for the admin’s approval."
    elif status != "denied" and await _request_access(user, context):
        msg = "This bot needs the admin’s approval. Your request has been sent, and you’ll get a message here once it’s reviewed."
    else:
        msg = "Sorry, you are not authorized to use this bot."
    if update.message:
        await update.message.reply_text(msg)
    elif update.callback_query:
        await update.callback_query.answer(msg, show_alert=True)
    return False

async def _require_admin(q: CallbackQuery, uid: int) -> bool:
    if uid != ADMIN_USER_ID:
        await q.edit_message_text("Only the admin can manage access.")
        return False
    return True

async def _access_decide(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str, approved: bool) -> None:
    """Admin answered an access request."""
    if not await _require_admin(q, uid):
        return
    try:
        target_id = int(arg)
    except ValueError:
        await q.edit_message_text("This access request no longer exists.")
        return
    # Only pending requests can be decided, so a stale button can't overturn an earlier decision
    decided = decide_access_request(target_id, approved)
    req = get_access_request(target_id)
    if not req or req[5] is None:
        await q.edit_message_text("This access request no longer exists.")
        return
    await q.edit_message_text(_access_request_text(req), parse_mode="HTML")
    if not decided:
        return

    notice = (
        "✅ Your access request was approved! Send /start to begin."
        if approved else
        "❌ Your access request was denied."
    )
    try:
        await context.bot.send_message(chat_id=target_id, text=notice)
    except TelegramError:
        pass  # User has blocked the bot; the decision is already stored

async def _access_approve(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    await _access_decide(q, context, uid, arg, approved=True)

async def _access_deny(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    await _access_decide(q, context, uid, arg, approved=False)

def _shareable_users(uid: int) -> list[tuple]:
    """Registered users other than `uid` who are allowed to use the bot."""
    return [u for u in get_other_users(uid) if _is_approved(u[0], u[3])]

# ---------- User management (admin) ----------

# Icon per access source, in the order users are listed
_ACCESS_ICONS = {"pending": "⏳", "approved": "✅", "env": "🔑", None: "▫️", "denied": "❌"}
_ACCESS_ORDER = list(_ACCESS_ICONS)

def _access_kind(user_id: int, status: str | None) -> str | None:
    """Where a user's access comes from; .env wins over the DB, as in _is_approved."""
    if user_id in AUTHORIZED_USERS:
        return "env"
    return status if status in _ACCESS_ICONS else None

def _user_details_text(req: tuple) -> str:
    user_id, status, decided_at = req[0], req[5], req[7]
    kind = _access_kind(user_id, status)
    if kind == "env":
        access = "🔑 Listed in AUTHORIZED_USERS (edit .env to change)"
    elif kind == "pending":
        access = "⏳ Waiting for approval"
    else:
        access = _decision_line(status, decided_at) or "▫️ No access"
    lines = [*_profile_lines(req), "", f"Access: {access}", f"📌 Favourites: {len(get_favourites(user_id))}"]
    return "\n".join(lines)

async def _get_managed_user(q: CallbackQuery, arg: str) -> tuple | None:
    """Look up a user for the admin from callback data (the admin can't manage themselves)."""
    try:
        req = get_access_request(int(arg))
    except ValueError:
        req = None
    if not req or req[0] == ADMIN_USER_ID:
        await q.edit_message_text("User not found.", reply_markup=InlineKeyboardMarkup([_back_exit_row("menu:users")]))
        return None
    return req

async def _show_users(q: CallbackQuery, uid: int) -> None:
    if not await _require_admin(q, uid):
        return
    set_state(uid, "manage_users")
    # Stable sort: within each group, users stay in name order
    users = sorted(get_other_users(uid), key=lambda u: _ACCESS_ORDER.index(_access_kind(u[0], u[3])))
    rows = [
        [InlineKeyboardButton(f"{_ACCESS_ICONS[_access_kind(u[0], u[3])]} {_user_label(u)}", callback_data=f"user:{u[0]}")]
        for u in users
    ]
    rows.append(_back_exit_row("menu:main"))
    text = (
        "👥 Users\n⏳ waiting · ✅ approved · 🔑 in .env · ▫️ no access · ❌ denied"
        if users else
        "No other users have messaged the bot yet."
    )
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

async def _user_manage(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    if not await _require_admin(q, uid):
        return
    req = await _get_managed_user(q, arg)
    if not req:
        return
    set_state(uid, "manage_users")
    user_id, status = req[0], req[5]
    rows: list[list[InlineKeyboardButton]] = []
    # .env access can't be changed from here, so offer no actions for those users
    if _access_kind(user_id, status) != "env":
        actions = []
        if status != "approved":
            actions.append(InlineKeyboardButton("✅ Approve", callback_data=f"user_approve:{user_id}"))
        if status != "denied":
            label = "🚫 Revoke access" if status == "approved" else "❌ Deny"
            actions.append(InlineKeyboardButton(label, callback_data=f"user_deny:{user_id}"))
        rows.append(actions)
    rows.append(_back_exit_row("menu:users"))
    await q.edit_message_text(_user_details_text(req), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))

async def _user_set_access(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str, approved: bool) -> None:
    if not await _require_admin(q, uid):
        return
    req = await _get_managed_user(q, arg)
    if not req:
        return
    user_id, previous = req[0], req[5]
    new_status = "approved" if approved else "denied"
    if _access_kind(user_id, previous) != "env" and previous != new_status:
        set_user_status(user_id, new_status)
        if approved:
            notice = "✅ You now have access to this bot. Send /start to begin."
        elif previous == "approved":
            notice = "🚫 Your access to this bot has been revoked."
        elif previous == "pending":
            notice = "❌ Your access request was denied."
        else:
            notice = None  # They never asked, so there's nothing to tell them
        if notice:
            try:
                await context.bot.send_message(chat_id=user_id, text=notice)
            except TelegramError:
                pass  # User has blocked the bot; the change is already stored
    await _user_manage(q, context, uid, arg)

async def _user_approve(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    await _user_set_access(q, context, uid, arg, approved=True)

async def _user_deny(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    await _user_set_access(q, context, uid, arg, approved=False)

# ---------- Entry / Exit ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return
    uid = update.effective_user.id
    set_state(uid, "main_menu")
    favs = get_favourites(uid)
    text = "Choose an option:"
    kb = _menu_kb(has_favs=bool(favs), uid=uid)
    if update.message:
        await update.message.reply_text(text, reply_markup=kb)
    else:
        # In case someone calls /start via a button—rare, but safe
        await update.callback_query.edit_message_text(text, reply_markup=kb)

async def exit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_auth(update, context):
        return
    uid = update.effective_user.id
    clear_state(uid)
    msg = "Exited. Type /start to begin again."
    if update.message:
        await update.message.reply_text(msg)
    else:
        await update.callback_query.edit_message_text(msg)

# ---------- Favourite management & sharing ----------
# Each action receives the callback data after its "<action>:" prefix.

async def _get_owned_fav(q: CallbackQuery, uid: int, arg: str) -> tuple | None:
    """Look up a favourite from callback data, only if it belongs to the user."""
    try:
        fav = get_favourite_by_id(uid, int(arg))
    except ValueError:
        fav = None
    if not fav:
        await q.edit_message_text("Favourite not found.", reply_markup=_exit_kb())
    return fav

async def _show_manage_list(q: CallbackQuery, uid: int) -> None:
    favs = get_favourites(uid)
    if not favs:
        set_state(uid, "main_menu")
        await q.edit_message_text("No favourites saved yet.", reply_markup=_menu_kb(False, uid=uid))
        return
    set_state(uid, "manage_favs")
    rows = [
        [InlineKeyboardButton(nickname, callback_data=f"manage:{fav_id}")]
        for (fav_id, nickname, _fp, _sh, _cell) in favs
    ]
    rows.append(_back_exit_row("menu:main"))
    await q.edit_message_text("Select a favourite to manage:", reply_markup=InlineKeyboardMarkup(rows))

async def _fav_manage(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    fav = await _get_owned_fav(q, uid, arg)
    if not fav:
        return
    fav_id, nickname, file_path, sheet_name, cell_coord = fav
    set_state(uid, "manage_favs")
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Rename", callback_data=f"rename:{fav_id}"),
            InlineKeyboardButton("📍 Change location", callback_data=f"relocate:{fav_id}"),
        ],
        [
            InlineKeyboardButton("📤 Share", callback_data=f"share:{fav_id}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"delete:{fav_id}"),
        ],
        _back_exit_row("menu:manage"),
    ])
    await q.edit_message_text(
        f"⭐ “{nickname}”\n{_fav_location(file_path, sheet_name, cell_coord)}\n\nWhat would you like to do?",
        reply_markup=kb
    )

async def _fav_rename(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    fav = await _get_owned_fav(q, uid, arg)
    if not fav:
        return
    fav_id, nickname, _fp, _sh, _cell = fav
    set_state(uid, "rename_fav", fav_id=fav_id)
    await q.edit_message_text(f"Type a new nickname for “{nickname}”:", reply_markup=_exit_kb())

async def _fav_relocate(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    fav = await _get_owned_fav(q, uid, arg)
    if not fav:
        return
    fav_id, nickname, _fp, _sh, _cell = fav
    files = list_excel_files(EXCEL_FOLDER)
    if not files:
        await q.edit_message_text("No Excel files found in the configured folder.", reply_markup=_exit_kb())
        return
    # Reuse the file → sheet → cell flow; the cell step updates this favourite instead of offering to save a new one
    clear_state(uid)
    set_state(uid, "choose_file", files=files, edit_fav_id=fav_id)
    await q.edit_message_text(
        f"Select the new file for “{nickname}”:",
        reply_markup=_list_kb("file", [p.name for p in files])
    )

async def _fav_delete(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    fav = await _get_owned_fav(q, uid, arg)
    if not fav:
        return
    fav_id, nickname, _fp, _sh, _cell = fav
    set_state(uid, "manage_favs")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 Yes, delete", callback_data=f"delete_confirm:{fav_id}"),
        InlineKeyboardButton("⬅️ Cancel", callback_data=f"manage:{fav_id}"),
    ]])
    await q.edit_message_text(f"Delete favourite “{nickname}”? This can’t be undone.", reply_markup=kb)

async def _fav_delete_confirm(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    fav = await _get_owned_fav(q, uid, arg)
    if not fav:
        return
    fav_id, nickname, _fp, _sh, _cell = fav
    delete_favourite(uid, fav_id)
    await q.edit_message_text(f"Favourite “{nickname}” deleted 🗑")
    favs = get_favourites(uid)
    set_state(uid, "main_menu")
    await q.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))

async def _fav_share(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    fav = await _get_owned_fav(q, uid, arg)
    if not fav:
        return
    fav_id, nickname, _fp, _sh, _cell = fav
    set_state(uid, "manage_favs")
    users = _shareable_users(uid)
    if not users:
        await q.edit_message_text(
            "There’s nobody to share with yet. Other users need to message the bot at least once first.",
            reply_markup=InlineKeyboardMarkup([_back_exit_row(f"manage:{fav_id}")])
        )
        return
    rows = [
        [InlineKeyboardButton(_user_label(u), callback_data=f"share_to:{fav_id}:{u[0]}")]
        for u in users
    ]
    rows.append(_back_exit_row(f"manage:{fav_id}"))
    await q.edit_message_text(f"Who do you want to share “{nickname}” with?", reply_markup=InlineKeyboardMarkup(rows))

async def _fav_share_to(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    fav_arg, _, target_arg = arg.partition(":")
    fav = await _get_owned_fav(q, uid, fav_arg)
    if not fav:
        return
    _fav_id, nickname, file_path, sheet_name, cell_coord = fav
    target = next((u for u in _shareable_users(uid) if str(u[0]) == target_arg), None)
    if not target:
        await q.edit_message_text("That user can’t receive shared favourites.", reply_markup=_exit_kb())
        return

    target_id = target[0]
    request_id = create_share_request(uid, target_id, nickname, file_path, sheet_name, cell_coord)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"share_accept:{request_id}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"share_deny:{request_id}"),
    ]])
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"📨 {_user_label(get_user(uid))} wants to share the favourite “{nickname}” with you.\n"
                f"{_fav_location(file_path, sheet_name, cell_coord)}"
            ),
            reply_markup=kb
        )
    except TelegramError:
        delete_share_request(request_id)
        await q.edit_message_text(
            f"Couldn’t reach {_user_label(target)}. They may have blocked the bot.",
            reply_markup=_exit_kb()
        )
        return

    await q.edit_message_text(f"📤 Sent “{nickname}” to {_user_label(target)}. You’ll be notified when they respond.")
    favs = get_favourites(uid)
    set_state(uid, "main_menu")
    await q.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))

async def _share_respond(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str, accepted: bool) -> None:
    """Recipient answered a share request. Leaves their conversation state alone: they may be mid-flow."""
    try:
        req = get_share_request(int(arg), uid)
    except ValueError:
        req = None
    # Deleting the request claims it, so it can only be answered once
    if not req or not delete_share_request(req[0]):
        await q.edit_message_text("This share request is no longer available.")
        return

    _req_id, from_uid, nickname, file_path, sheet_name, cell_coord = req
    sender = get_user(from_uid)
    sender_label = _user_label(sender) if sender else "another user"
    me = _user_label(get_user(uid))
    if not accepted:
        await q.edit_message_text(f"❌ You declined “{nickname}” from {sender_label}.")
        notice = f"❌ {me} declined your favourite “{nickname}”."
    elif favourite_exists(uid, file_path, sheet_name, cell_coord):
        await q.edit_message_text(
            f"You already have {sheet_name}!{cell_coord} in your favourites, so “{nickname}” wasn’t added again."
        )
        notice = f"✅ {me} accepted your favourite “{nickname}”."
    else:
        add_favourite(uid, nickname, file_path, sheet_name, cell_coord)
        await q.edit_message_text(f"✅ “{nickname}” from {sender_label} was added to your favourites.")
        notice = f"✅ {me} accepted your favourite “{nickname}”."

    try:
        await context.bot.send_message(chat_id=from_uid, text=notice)
    except TelegramError:
        pass  # Sender has blocked the bot; the share itself already succeeded

async def _share_accept(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    await _share_respond(q, context, uid, arg, accepted=True)

async def _share_deny(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, uid: int, arg: str) -> None:
    await _share_respond(q, context, uid, arg, accepted=False)

# Callback actions routed by their "<action>:" prefix
_CALLBACK_ACTIONS = {
    "access_approve": _access_approve,
    "access_deny": _access_deny,
    "user": _user_manage,
    "user_approve": _user_approve,
    "user_deny": _user_deny,
    "manage": _fav_manage,
    "rename": _fav_rename,
    "relocate": _fav_relocate,
    "delete": _fav_delete,
    "delete_confirm": _fav_delete_confirm,
    "share": _fav_share,
    "share_to": _fav_share_to,
    "share_accept": _share_accept,
    "share_deny": _share_deny,
}

# ---------- Callback router ----------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Single router for all callback buttons."""
    if not await _check_auth(update, context):
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
    if data == "menu:main":
        favs = get_favourites(uid)
        set_state(uid, "main_menu")
        await q.edit_message_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
        return

    if data == "menu:manage":
        await _show_manage_list(q, uid)
        return

    if data == "menu:users":
        await _show_users(q, uid)
        return

    if data == "menu:files":
        files = list_excel_files(EXCEL_FOLDER)
        if not files:
            await q.edit_message_text("No Excel files found in the configured folder.", reply_markup=_exit_kb())
            set_state(uid, "main_menu")
            return
        # store list in state to avoid long callback_data
        # (fresh state, so a plain lookup never inherits an abandoned "change location" edit)
        clear_state(uid)
        set_state(uid, "choose_file", files=files)
        await q.edit_message_text(
            "Select a file:",
            reply_markup=_list_kb("file", [p.name for p in files])
        )
        return

    if data == "menu:favs":
        favs = get_favourites(uid)
        if not favs:
            await q.edit_message_text("No favourites saved yet.", reply_markup=_menu_kb(False, uid=uid))
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

        fav = get_favourite_by_id(uid, fav_id)
        if not fav:
            await q.edit_message_text("Favourite not found.", reply_markup=_exit_kb())
            return

        _id, nickname, file_path, sheet_name, cell_coord = fav
        value = read_cell(Path(file_path), sheet_name, cell_coord)
        await q.edit_message_text(f"Value for *{nickname}* ({sheet_name}!{cell_coord}): {value}", parse_mode="Markdown")
        # Back to main menu
        favs = get_favourites(uid)
        await q.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
        set_state(uid, "main_menu")
        return

    # Access requests, favourite management & sharing
    action, _, arg = data.partition(":")
    if action in _CALLBACK_ACTIONS:
        await _CALLBACK_ACTIONS[action](q, context, uid, arg)
        return

    # Unknown callback
    await q.edit_message_text("Sorry, I didn’t understand that action.", reply_markup=_exit_kb())

# ---------- Text messages ----------

_CELL_RE = re.compile(r"^[A-Za-z]+\d+$")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free text for cell coordinates or nickname."""
    if not await _check_auth(update, context):
        return
    uid = update.effective_user.id
    st = get_state(uid)

    # No state → show main menu on any text
    if not st:
        favs = get_favourites(uid)
        set_state(uid, "main_menu")
        await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
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

        # Changing an existing favourite's location (from Manage favourites)
        edit_fav_id = st.get("edit_fav_id")
        if edit_fav_id is not None:
            if update_favourite_location(uid, edit_fav_id, str(file_path), sheet_name, coord):
                await update.message.reply_text(f"Favourite updated ✅\n{_fav_location(str(file_path), sheet_name, coord)}")
            else:
                await update.message.reply_text("Favourite not found.")
            favs = get_favourites(uid)
            clear_state(uid)
            set_state(uid, "main_menu")
            await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
            return

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
            await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
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
        await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
        return

    # Expecting a new nickname for an existing favourite
    if step == "rename_fav":
        nickname = update.message.text.strip()
        if update_favourite_nickname(uid, st["fav_id"], nickname):
            await update.message.reply_text(f"Favourite renamed to “{nickname}” ✅")
        else:
            await update.message.reply_text("Favourite not found.")
        favs = get_favourites(uid)
        set_state(uid, "main_menu")
        await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
        return

    # Fallback: show menu
    favs = get_favourites(uid)
    set_state(uid, "main_menu")
    await update.message.reply_text("Choose an option:", reply_markup=_menu_kb(has_favs=bool(favs), uid=uid))
