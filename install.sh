#!/usr/bin/env bash
# SCION one-liner installer.
#
# Usage (from any Linux VM with internet access):
#   curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/SCION/main/install.sh | bash
#
# What it does:
#   1. Verifies it's running on a supported Linux distribution.
#   2. Installs Docker Engine + Compose plugin if missing.
#   3. Creates /opt/scion as the deploy root.
#   4. Downloads docker-compose.yml + nginx.conf from this repo.
#   5. Prompts for region, GROQ key, public port (with sensible defaults).
#   6. Auto-generates a strong API_KEY.
#   7. Pulls images from GHCR and brings the stack up.
#   8. Prints the URL + admin key on success.
#
# Idempotent: re-running on an existing install only refreshes the
# compose files and restarts containers — never overwrites .env.

set -euo pipefail

# ──── Constants ────
REPO_RAW="https://raw.githubusercontent.com/GuilleAlbella/SCION/main"
INSTALL_DIR="/opt/scion"
COMPOSE_FILES=("docker-compose.yml" "docker/nginx.conf" ".env.example")

# ──── Helpers ────
c_red()    { printf "\033[31m%s\033[0m" "$*"; }
c_green()  { printf "\033[32m%s\033[0m" "$*"; }
c_yellow() { printf "\033[33m%s\033[0m" "$*"; }
c_blue()   { printf "\033[34m%s\033[0m" "$*"; }

step()  { echo; echo "$(c_blue "▶") $*"; }
ok()    { echo "  $(c_green "✓") $*"; }
warn()  { echo "  $(c_yellow "!") $*"; }
fail()  { echo "  $(c_red "✗") $*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }

# ──── Pre-flight ────
step "SCION installer"

if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
  fail "This script needs root privileges (uses sudo). Run as root or with passwordless sudo."
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

require_cmd curl
require_cmd uname

if [ "$(uname -s)" != "Linux" ]; then
  fail "Only Linux is supported. Detected: $(uname -s)"
fi

# Detect distro family.
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  DISTRO_ID="${ID:-unknown}"
  DISTRO_LIKE="${ID_LIKE:-}"
else
  fail "Cannot read /etc/os-release; unsupported distro."
fi

ok "Detected distro: ${PRETTY_NAME:-$DISTRO_ID}"

# ──── Step 1: install Docker if missing ────
install_docker_debian() {
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq ca-certificates curl gnupg
  $SUDO install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${DISTRO_ID}/gpg" | \
    $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${DISTRO_ID} $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

install_docker_rhel() {
  $SUDO dnf install -y -q dnf-plugins-core || $SUDO yum install -y -q yum-utils
  if command -v dnf >/dev/null; then
    $SUDO dnf config-manager --add-repo "https://download.docker.com/linux/${DISTRO_ID}/docker-ce.repo"
    $SUDO dnf install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
  else
    $SUDO yum-config-manager --add-repo "https://download.docker.com/linux/${DISTRO_ID}/docker-ce.repo"
    $SUDO yum install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
  fi
}

step "Checking Docker"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  ok "Docker + Compose plugin already installed ($(docker --version | awk '{print $3}'))"
else
  warn "Docker missing — installing now"
  case "$DISTRO_ID" in
    ubuntu|debian)         install_docker_debian ;;
    rhel|centos|rocky|almalinux|fedora) install_docker_rhel ;;
    *)
      if [[ "$DISTRO_LIKE" == *"debian"* ]]; then install_docker_debian
      elif [[ "$DISTRO_LIKE" == *"rhel"* || "$DISTRO_LIKE" == *"fedora"* ]]; then install_docker_rhel
      else fail "Unsupported distro: $DISTRO_ID. Install Docker manually then re-run."
      fi
      ;;
  esac
  $SUDO systemctl enable --now docker
  ok "Docker installed"
fi

# ──── Step 2: deploy directory ────
step "Preparing deploy directory at $INSTALL_DIR"
$SUDO mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/docker"
$SUDO chown -R "$(id -u):$(id -g)" "$INSTALL_DIR" 2>/dev/null || true
ok "$INSTALL_DIR ready"

# ──── Step 3: download compose + nginx config ────
step "Downloading compose files from $REPO_RAW"
for f in "${COMPOSE_FILES[@]}"; do
  curl -fsSL "$REPO_RAW/$f" -o "$INSTALL_DIR/$f"
  ok "$f"
done

# ──── Step 4: configure ────
ENV_FILE="$INSTALL_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  warn ".env already exists — keeping current values, skipping prompts"
else
  step "Configuration (press Enter to accept defaults)"
  read -r -p "  Region [us-east-1]: " REGION
  REGION="${REGION:-us-east-1}"

  read -r -p "  Public port [80]: " PORT
  PORT="${PORT:-80}"

  read -r -p "  Groq API key (TAISA — leave empty to configure later): " GROQ_KEY

  # API_KEY: auto-generate a strong one. User never types this.
  if command -v openssl >/dev/null; then
    GENERATED_KEY="$(openssl rand -hex 32)"
  else
    GENERATED_KEY="$(head -c 32 /dev/urandom | xxd -p -c 64)"
  fi

  cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
  # Fill in the values (sed in-place; using | as separator to avoid
  # collisions with values that contain /).
  sed -i "s|^DATA_REGION=.*|DATA_REGION=$REGION|"           "$ENV_FILE"
  sed -i "s|^SCION_PUBLIC_PORT=.*|SCION_PUBLIC_PORT=$PORT|" "$ENV_FILE"
  sed -i "s|^API_KEY=.*|API_KEY=$GENERATED_KEY|"            "$ENV_FILE"
  if [ -n "${GROQ_KEY:-}" ]; then
    sed -i "s|^GROQ_API_KEY=.*|GROQ_API_KEY=$GROQ_KEY|" "$ENV_FILE"
  fi

  chmod 600 "$ENV_FILE"
  ok "Wrote $ENV_FILE (mode 600)"
fi

# ──── Step 5: pull + start ────
step "Pulling images from GHCR"
(cd "$INSTALL_DIR" && $SUDO docker compose pull)
ok "Images pulled"

step "Starting SCION"
(cd "$INSTALL_DIR" && $SUDO docker compose up -d)

# ──── Step 6: report ────
sleep 3
PORT_FROM_ENV="$(grep -E '^SCION_PUBLIC_PORT=' "$ENV_FILE" | cut -d= -f2)"
KEY_FROM_ENV="$(grep -E '^API_KEY='            "$ENV_FILE" | cut -d= -f2)"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-localhost}"

echo
c_green "═══════════════════════════════════════════════════════════"; echo
c_green "  SCION is up"; echo
c_green "═══════════════════════════════════════════════════════════"; echo
echo
echo "  URL:        http://$IP:$PORT_FROM_ENV"
echo "  Admin key:  $KEY_FROM_ENV"
echo "  Config:     $ENV_FILE"
echo
echo "  Status:   cd $INSTALL_DIR && docker compose ps"
echo "  Logs:     cd $INSTALL_DIR && docker compose logs -f"
echo "  Update:   curl -fsSL $REPO_RAW/update.sh | bash"
echo "  Stop:     cd $INSTALL_DIR && docker compose down"
echo
echo "  Watchtower will auto-pull new releases every 6h. To force an"
echo "  upgrade now, run the Update command above."
echo
