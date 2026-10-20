#!/usr/bin/env bash
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

# Deploy gridbot on the server: update the code, install dependencies,
# back up the database and restart the systemd service.
#
# Usage:
#   ./deploy.sh            deploy the latest origin/main
#   ./deploy.sh <commit>   deploy (or roll back to) a specific commit or tag
#
# Environment overrides:
#   GRIDBOT_SERVICE   systemd service name (default: auto-detected)
#   GRIDBOT_BRANCH    branch to deploy (default: main)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${GRIDBOT_BRANCH:-main}"
BACKUP_DIR="$REPO_DIR/backups"
KEEP_BACKUPS=10
UNIT_DIRS="/etc/systemd/system /lib/systemd/system /usr/lib/systemd/system"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mxx  %s\033[0m\n' "$*" >&2; exit 1; }

# Find the systemd service that runs this checkout (by its path, else by name)
detect_service() {
    local units="" pattern dir
    for pattern in "$REPO_DIR" gridbot; do
        for dir in $UNIT_DIRS; do
            units="$units $(grep -lsF "$pattern" "$dir"/*.service || true)"
        done
        units=$(printf '%s\n' $units | xargs -n1 basename 2>/dev/null | sort -u || true)
        [ -n "$units" ] && break
    done
    case "$(printf '%s\n' $units | grep -c .)" in
        1) printf '%s\n' "$units" ;;
        0) die "No systemd service for gridbot found. Set GRIDBOT_SERVICE=<name>." ;;
        *) die "Several candidate services found ($(echo $units)). Set GRIDBOT_SERVICE=<name>." ;;
    esac
}

main() {
    local target="${1:-}"
    local sudo=""
    [ "$(id -u)" -eq 0 ] || sudo="sudo"
    cd "$REPO_DIR"

    local service="${GRIDBOT_SERVICE:-}"
    [ -n "$service" ] || service=$(detect_service)
    info "Service: $service"

    # --- Code ---
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        git status --short --untracked-files=no >&2
        die "Local changes to tracked files. Commit, stash or discard them first."
    fi
    local prev new
    prev=$(git rev-parse --short HEAD)
    if [ -n "$target" ]; then
        info "Checking out $target"
        git fetch --quiet origin
        git checkout --quiet --detach "$target"
    else
        info "Updating to the latest origin/$BRANCH"
        git fetch --quiet origin "$BRANCH"
        git checkout --quiet "$BRANCH"
        git merge --quiet --ff-only "origin/$BRANCH"
    fi
    new=$(git rev-parse --short HEAD)
    if [ "$prev" = "$new" ]; then
        info "Already at $new, restarting anyway"
    else
        info "$prev -> $new"
        git --no-pager log --oneline --no-decorate "$prev..$new" | sed 's/^/      /'
    fi
    trap 'warn "Deploy stopped before the restart: the service is still running $prev. To put the files back: git checkout $prev"' ERR

    # --- Dependencies, into the interpreter the service runs with ---
    local python
    python=$(systemctl show -p ExecStart --value "$service" | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
    case "$(basename "${python:-none}")" in
        python*) ;;
        *) python="$REPO_DIR/.venv/bin/python" ;;
    esac
    if [ -x "$python" ] && "$python" -c 'import sys; sys.exit(sys.prefix == sys.base_prefix)'; then
        info "Installing dependencies ($python)"
        "$python" -m pip install --quiet --disable-pip-version-check -r requirements.txt
    else
        warn "No virtualenv found for $service; skipping dependency install. Install requirements.txt manually if it changed."
        python=python3
    fi

    # --- Database backup (DB_PATH is relative to the service's working directory) ---
    local db_path workdir backup
    db_path=$(sed -n 's/^DB_PATH=//p' .env 2>/dev/null | tail -n1 | tr -d "\"'\r")
    db_path="${db_path:-favourites.db}"
    if [ "${db_path#/}" = "$db_path" ]; then
        workdir=$(systemctl show -p WorkingDirectory --value "$service")
        db_path="${workdir:-$REPO_DIR}/$db_path"
    fi
    if [ -f "$db_path" ]; then
        mkdir -p "$BACKUP_DIR"
        backup="$BACKUP_DIR/$(basename "$db_path" .db)-$(date +%Y%m%d-%H%M%S)-$prev.db"
        # SQLite's backup API gives a consistent copy even while the bot is writing
        "$python" -c 'import sqlite3, sys; src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()' "$db_path" "$backup"
        info "Database backed up to ${backup#"$REPO_DIR"/}"
        ls -1t "$BACKUP_DIR"/*.db | tail -n +$((KEEP_BACKUPS + 1)) | while read -r old; do rm -f -- "$old"; done
    else
        warn "Database $db_path not found; skipping backup."
    fi
    trap - ERR

    # --- Restart and make sure it stays up ---
    info "Restarting $service"
    $sudo systemctl restart "$service"
    local restarts_before restarts_after state
    restarts_before=$(systemctl show -p NRestarts --value "$service")
    sleep 5
    state=$(systemctl is-active "$service" || true)
    restarts_after=$(systemctl show -p NRestarts --value "$service")
    if [ "$state" != "active" ] || [ "$restarts_before" != "$restarts_after" ]; then
        warn "$service is not running cleanly (state: $state). Recent logs:"
        $sudo journalctl -u "$service" -n 40 --no-pager || true
        die "Deploy of $new failed. Roll back with: ./deploy.sh $prev"
    fi
    info "Deployed $new: $service is running"
}

main "$@"
