#!/usr/bin/env bash
# SCION uninstaller. Stops containers and optionally wipes the volume
# (which contains the SQLite database).
#
#   curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/SCION/main/uninstall.sh | bash

set -euo pipefail

INSTALL_DIR="/opt/scion"

if [ ! -d "$INSTALL_DIR" ]; then
  echo "Nothing to uninstall — $INSTALL_DIR doesn't exist."
  exit 0
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

echo "▶ Stopping SCION containers"
(cd "$INSTALL_DIR" && $SUDO docker compose down)

read -r -p "  Also delete the data volume (SQLite DB will be lost)? [y/N] " WIPE
if [[ "${WIPE:-}" =~ ^[Yy]$ ]]; then
  (cd "$INSTALL_DIR" && $SUDO docker compose down -v)
  echo "  ✓ Volume removed"
fi

read -r -p "  Remove $INSTALL_DIR (config + .env)? [y/N] " WIPE_DIR
if [[ "${WIPE_DIR:-}" =~ ^[Yy]$ ]]; then
  $SUDO rm -rf "$INSTALL_DIR"
  echo "  ✓ $INSTALL_DIR removed"
fi

echo "✓ SCION uninstalled"
