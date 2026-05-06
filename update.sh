#!/usr/bin/env bash
# SCION manual updater. Watchtower normally handles this every 6h —
# this script is for the impatient or for environments where
# Watchtower is disabled.
#
#   curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/SCION/main/update.sh | bash

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/GuilleAlbella/SCION/main"
INSTALL_DIR="/opt/scion"

if [ ! -d "$INSTALL_DIR" ]; then
  echo "✗ $INSTALL_DIR not found. Run install.sh first." >&2
  exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

echo "▶ Refreshing compose + nginx config from $REPO_RAW"
curl -fsSL "$REPO_RAW/docker-compose.yml" -o "$INSTALL_DIR/docker-compose.yml"
curl -fsSL "$REPO_RAW/docker/nginx.conf" -o "$INSTALL_DIR/docker/nginx.conf"

echo "▶ Pulling latest images"
(cd "$INSTALL_DIR" && $SUDO docker compose pull)

echo "▶ Recreating containers"
(cd "$INSTALL_DIR" && $SUDO docker compose up -d)

echo "✓ SCION updated. Current containers:"
(cd "$INSTALL_DIR" && $SUDO docker compose ps)
