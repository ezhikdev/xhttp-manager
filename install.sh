#!/usr/bin/env bash
set -Eeuo pipefail

NON_INTERACTIVE=0
case "${1:-}" in
  --non-interactive) NON_INTERACTIVE=1 ;;
  "") ;;
  *) echo "Unknown option: $1"; exit 1 ;;
esac

[[ ${EUID} -eq 0 ]] || { echo 'Run as root: sudo ./install.sh'; exit 1; }
source /etc/os-release
case "${ID}:${VERSION_ID}" in
  ubuntu:22.04|ubuntu:24.04|debian:12) ;;
  *) echo "Unsupported OS: ${PRETTY_NAME}. Supported: Ubuntu 22.04/24.04, Debian 12."; exit 1 ;;
esac

APP=xhttp-manager
APP_USER=xhttpmgr
APP_DIR=/opt/${APP}
ETC_DIR=/etc/${APP}
BACKUP_DIR=/var/backups/${APP}
DEFAULT_PORT=8765

echo 'Installing required packages…'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx python3 python3-venv python3-pip openssl sudo iproute2 curl ca-certificates tar

SOURCE_DIR=""
SCRIPT_SOURCE=${BASH_SOURCE[0]:-}
if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
  SOURCE_DIR=$(cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)
fi

DOWNLOAD_DIR=""
cleanup() {
  if [[ "$DOWNLOAD_DIR" == /tmp/xhttp-manager.* && -d "$DOWNLOAD_DIR" ]]; then
    rm -rf -- "$DOWNLOAD_DIR"
  fi
}
trap cleanup EXIT

if [[ ! -f "$SOURCE_DIR/requirements.txt" || ! -d "$SOURCE_DIR/app" ]]; then
  echo 'Downloading XHTTP Manager…'
  DOWNLOAD_DIR=$(mktemp -d /tmp/xhttp-manager.XXXXXX)
  curl -fsSL --retry 3 \
    https://github.com/ezhikdev/xhttp-manager/archive/refs/heads/main.tar.gz \
    -o "$DOWNLOAD_DIR/source.tar.gz"
  tar -xzf "$DOWNLOAD_DIR/source.tar.gz" -C "$DOWNLOAD_DIR" --strip-components=1
  SOURCE_DIR=$DOWNLOAD_DIR
fi

if (( NON_INTERACTIVE )); then
  PANEL_USER=${PANEL_USER:-admin}
  PANEL_PASS=${PANEL_PASS:-}
  PANEL_PORT=${PANEL_PORT:-$DEFAULT_PORT}
else
  read -rp "Panel login [admin]: " PANEL_USER
  PANEL_USER=${PANEL_USER:-admin}
  read -rsp "Panel password (Enter to generate): " PANEL_PASS; echo
  read -rp "Panel port [${DEFAULT_PORT}]: " PANEL_PORT
  PANEL_PORT=${PANEL_PORT:-$DEFAULT_PORT}
fi

[[ "$PANEL_USER" =~ ^[A-Za-z0-9_.@-]{1,64}$ ]] || { echo 'Login may contain only letters, numbers, dot, underscore, @ and hyphen.'; exit 1; }
if [[ -z "$PANEL_PASS" ]]; then PANEL_PASS=$(openssl rand -base64 24 | tr -d '=+/\n' | cut -c1-20); GENERATED_PASS=1; fi
[[ "$PANEL_PORT" =~ ^[0-9]+$ ]] && (( PANEL_PORT >= 1 && PANEL_PORT <= 65535 )) || { echo 'Invalid port.'; exit 1; }

PORT_LISTENER=$(ss -H -ltnp "sport = :${PANEL_PORT}" || true)
if [[ -n "$PORT_LISTENER" ]]; then
  MANAGER_PID=$(systemctl show xhttp-manager --property MainPID --value 2>/dev/null || true)
  if [[ -n "$MANAGER_PID" && "$MANAGER_PID" != "0" && "$PORT_LISTENER" == *"pid=${MANAGER_PID},"* ]]; then
    echo "Existing XHTTP Manager detected on port ${PANEL_PORT}; it will be restarted after the update."
  else
    echo "Port ${PANEL_PORT} is used by another process:"
    echo "$PORT_LISTENER"
    echo 'Refusing to stop an unrelated service automatically.'
    exit 1
  fi
fi

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"
tar -C /etc -czf "$BACKUP_DIR/nginx-${STAMP}.tar.gz" nginx
echo "Existing nginx configuration backed up to $BACKUP_DIR/nginx-${STAMP}.tar.gz"

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR" "$ETC_DIR/nginx-revisions" "$ETC_DIR/backups"
install -m 0750 -o "$APP_USER" -g "$APP_USER" -d "$ETC_DIR/nginx-revisions" "$ETC_DIR/backups"
install -m 0644 -o root -g root "$SOURCE_DIR/requirements.txt" "$APP_DIR/requirements.txt"
rm -rf "$APP_DIR/app"
cp -a "$SOURCE_DIR/app" "$APP_DIR/app"
chown -R root:root "$APP_DIR/app"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --disable-pip-version-check --no-cache-dir -q -r "$APP_DIR/requirements.txt"

HASH=$(cd "$APP_DIR" && PANEL_PASS="$PANEL_PASS" "$APP_DIR/venv/bin/python" -c 'import os; from app.main import password_hash; print(password_hash(os.environ["PANEL_PASS"]))')
cat > "$ETC_DIR/config.env" <<EOF
PANEL_USER=${PANEL_USER}
PANEL_PASSWORD_HASH=${HASH}
PANEL_PORT=${PANEL_PORT}
PANEL_PATH=/xhttp-manager
LOGIN_MAX_ATTEMPTS=3
LOGIN_BLOCK_SECONDS=300
XHTTP_MANAGER_DIR=${ETC_DIR}
EOF
chmod 0640 "$ETC_DIR/config.env"
chown root:"$APP_USER" "$ETC_DIR/config.env"
[[ -f "$ETC_DIR/origins.json" ]] || printf '[]\n' > "$ETC_DIR/origins.json"
chown "$APP_USER":"$APP_USER" "$ETC_DIR/origins.json"
chmod 0640 "$ETC_DIR/origins.json"

cat > /etc/nginx/conf.d/xhttp-manager.conf <<EOF
# Managed by XHTTP Manager. Do not edit generated origin files directly.
include ${ETC_DIR}/nginx-revisions/current/*.conf;
EOF
mkdir -p "$ETC_DIR/nginx-revisions/initial"
if [[ ! -e "$ETC_DIR/nginx-revisions/current" && ! -L "$ETC_DIR/nginx-revisions/current" ]]; then
  printf '[]\n' > "$ETC_DIR/nginx-revisions/initial/origins.json"
  chown "$APP_USER":"$APP_USER" "$ETC_DIR/nginx-revisions/initial/origins.json"
  ln -s "$ETC_DIR/nginx-revisions/initial" "$ETC_DIR/nginx-revisions/current"
  chown -h "$APP_USER":"$APP_USER" "$ETC_DIR/nginx-revisions/current"
fi

NGINX_BIN=$(command -v nginx)
SYSTEMCTL_BIN=$(command -v systemctl)
cat > /etc/sudoers.d/xhttp-manager <<EOF
${APP_USER} ALL=(root) NOPASSWD: ${NGINX_BIN} -t, ${SYSTEMCTL_BIN} reload nginx
EOF
chmod 0440 /etc/sudoers.d/xhttp-manager
visudo -cf /etc/sudoers.d/xhttp-manager >/dev/null

cat > /etc/systemd/system/xhttp-manager.service <<EOF
[Unit]
Description=XHTTP Manager web panel
After=network.target

[Service]
User=${APP_USER}
Group=${APP_USER}
EnvironmentFile=${ETC_DIR}/config.env
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \${PANEL_PORT}
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

nginx -t
systemctl daemon-reload
systemctl enable xhttp-manager
systemctl restart xhttp-manager
systemctl is-active --quiet xhttp-manager
SERVER_IP=$(hostname -I | awk '{print $1}')
echo
echo 'XHTTP Manager is running.'
echo "URL: http://${SERVER_IP}:${PANEL_PORT}/xhttp-manager"
echo "Login: ${PANEL_USER}"
echo "Password: ${PANEL_PASS}"
[[ ${GENERATED_PASS:-0} -eq 1 ]] && echo '(Password was generated; save it now.)'
