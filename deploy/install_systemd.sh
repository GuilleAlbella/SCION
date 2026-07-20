#!/usr/bin/env bash
# ============================================================
#  SCION — instalar / actualizar el servicio systemd
#
#  Instala scion.service de forma que el stack docker-compose
#  arranque automáticamente al iniciar el servidor Linux.
#
#  Uso:
#    sudo ./install_systemd.sh              # instala en /opt/scion (default)
#    SCION_INSTALL_DIR=/var/opt/scion sudo ./install_systemd.sh
#    sudo ./install_systemd.sh --uninstall  # elimina el servicio
# ============================================================
set -euo pipefail

UNIT_NAME="scion"
INSTALL_DIR="${SCION_INSTALL_DIR:-/opt/scion}"
UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/systemd/${UNIT_NAME}.service"
UNIT_DST="/etc/systemd/system/${UNIT_NAME}.service"

c_green() { printf "\033[32m%s\033[0m\n" "$*"; }
c_red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }
ok()  { echo "  ✓ $*"; }
err() { c_red "  ✗ $*"; exit 1; }

[[ $EUID -eq 0 ]] || err "Este script debe ejecutarse como root (sudo)."
[[ -f "$UNIT_SRC" ]] || err "No se encontró $UNIT_SRC — ejecuta desde el directorio deploy/."

# ── Uninstall path ──────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  echo "Desinstalando scion.service..."
  systemctl stop  "${UNIT_NAME}.service" 2>/dev/null || true
  systemctl disable "${UNIT_NAME}.service" 2>/dev/null || true
  rm -f "${UNIT_DST}"
  systemctl daemon-reload
  c_green "Servicio ${UNIT_NAME}.service eliminado."
  exit 0
fi

# ── Install path ────────────────────────────────────────────
echo "Instalando scion.service → ${UNIT_DST}"
echo "  WorkingDirectory = ${INSTALL_DIR}"

# Substitute install dir placeholder in the unit file.
sed "s|/opt/scion|${INSTALL_DIR}|g" "${UNIT_SRC}" > "${UNIT_DST}"
chmod 644 "${UNIT_DST}"
ok "Unit file escrito en ${UNIT_DST}"

systemctl daemon-reload
ok "systemd recargado"

systemctl enable "${UNIT_NAME}.service"
ok "Servicio habilitado (arranca al inicio)"

systemctl start "${UNIT_NAME}.service"
ok "Servicio iniciado"

echo
c_green "SCION systemd service instalado correctamente."
echo
systemctl status "${UNIT_NAME}.service" --no-pager -l
