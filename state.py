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

from typing import Any

# Simple in-memory per-user state store
_user_states: dict[int, dict[str, Any]] = {}

def set_state(user_id: int, step: str, **kwargs) -> None:
    st = _user_states.get(user_id, {})
    st.update({"step": step, **kwargs})
    _user_states[user_id] = st

def get_state(user_id: int) -> dict[str, Any] | None:
    return _user_states.get(user_id)

def clear_state(user_id: int) -> None:
    _user_states.pop(user_id, None)

