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

if __name__ == "__main__" and __package__ is None:
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gridbot"

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from .config import TOKEN
from .database import init_db
from .handlers import start, exit_cmd, handle_text, on_callback

def main() -> None:
    if not TOKEN:
        raise RuntimeError("TOKEN is not set. Please set it in your environment or .env file.")

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("exit", exit_cmd))

    # Buttons / callbacks (single router)
    app.add_handler(CallbackQueryHandler(on_callback))

    # Text input (cell coordinate / nickname / or show menu)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ gridbot is running…")
    app.run_polling()

if __name__ == "__main__":
    main()
