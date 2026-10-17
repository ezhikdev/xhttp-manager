#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
ACTIVATE_FIREWALL=0
for arg in "$@"; do
  case "$arg" in
    --non-interactive) ;;
    --activate-firewall) ACTIVATE_FIREWALL=1 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo 'Run as root: sudo bash install.sh'; exit 1; }
# shellcheck disable=SC1091
source /etc/os-release
case "$ID:$VERSION_ID" in
  ubuntu:22.04|ubuntu:24.04|debian:12) ;;
  *) echo "Unsupported OS: $PRETTY_NAME"; exit 1 ;;
esac
APP_DIR=/opt/xhttp-manager
ETC_DIR=/etc/xhttp-manager
APP_USER=xhttpmgr
STAMP=$(date -u +%Y%m%dT%H%M%S)-$$
RELEASE=$APP_DIR/releases/$STAMP
BACKUP=/var/backups/xhttp-manager/$STAMP
DOWNLOAD=""
SOURCE=""
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then SOURCE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); fi
cleanup() {
  if [[ "$DOWNLOAD" == /tmp/xhttp-manager.* && -d "$DOWNLOAD" ]]; then rm -rf -- "$DOWNLOAD"; fi
}
trap cleanup EXIT
LISTENER=$(ss -H -ltnp 'sport = :80' || true)
if [[ -n "$LISTENER" && "$LISTENER" != *'"nginx"'* ]]; then
  echo 'Port 80 belongs to another service. No service has been stopped.'
  echo 'Configure that reverse proxy to forward the random path to /run/xhttp-manager/panel.sock, or migrate HTTP to nginx first.'
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
if ! command -v nginx >/dev/null; then
  [[ ! -e /usr/sbin/policy-rc.d ]] || { echo 'Install nginx using the existing policy-rc.d policy, then rerun.'; exit 1; }
  printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
  chmod 0755 /usr/sbin/policy-rc.d
  trap 'rm -f /usr/sbin/policy-rc.d; cleanup' EXIT
  apt-get install -y -qq nginx python3 python3-venv python3-pip sudo nftables iproute2 curl ca-certificates tar
  rm -f /usr/sbin/policy-rc.d
  trap cleanup EXIT
else
  apt-get install -y -qq python3 python3-venv python3-pip sudo nftables iproute2 curl ca-certificates tar
fi
nginx -t
if [[ ! -f "$SOURCE/requirements.txt" || ! -d "$SOURCE/app" ]]; then
  DOWNLOAD=$(mktemp -d /tmp/xhttp-manager.XXXXXX)
  curl -fsSL --retry 3 'https://github.com/ezhikdev/xhttp-manager/archive/refs/heads/main.tar.gz' -o "$DOWNLOAD/source.tar.gz"
  tar -xzf "$DOWNLOAD/source.tar.gz" -C "$DOWNLOAD" --strip-components=1
  SOURCE=$DOWNLOAD
fi
mkdir -p "$BACKUP"
chmod 0700 "$BACKUP"
MANAGED=(/etc/nginx/conf.d/xhttp-manager.conf /etc/nginx/sites-enabled/xhttp-manager.conf
  /etc/systemd/system/xhttp-manager.service /etc/systemd/system/xhttp-manager-firewall.service
  /etc/sudoers.d/xhttp-manager /usr/local/sbin/xhttp-manager-firewall /usr/local/sbin/xhttp-manager-nginx)
for path in "${MANAGED[@]}"; do
  if [[ -e "$path" || -L "$path" ]]; then cp -a --parents "$path" "$BACKUP"; fi
done
[[ ! -d "$ETC_DIR" ]] || tar -C /etc -czf "$BACKUP/config.tar.gz" xhttp-manager
OLD_APP=$(readlink "$APP_DIR/app" || true)
OLD_VENV=$(readlink "$APP_DIR/venv" || true)
OLD_RUNNING=0
systemctl is-active --quiet xhttp-manager && OLD_RUNNING=1
OLD_PANEL_ENABLED=0
OLD_FIREWALL_ENABLED=0
systemctl is-enabled --quiet xhttp-manager 2>/dev/null && OLD_PANEL_ENABLED=1
systemctl is-enabled --quiet xhttp-manager-firewall 2>/dev/null && OLD_FIREWALL_ENABLED=1
COMMITTED=0
CHANGED=0
rollback_install() {
  local rc=$?
  trap - ERR
  if (( CHANGED && ! COMMITTED )); then
    echo "Installation failed; restoring product files from $BACKUP."
    systemctl stop xhttp-manager || true
    systemctl disable xhttp-manager xhttp-manager-firewall 2>/dev/null || true
    for path in "${MANAGED[@]}"; do
      rm -f -- "$path"
      if [[ -e "$BACKUP$path" || -L "$BACKUP$path" ]]; then cp -a "$BACKUP$path" "$path"; fi
    done
    if [[ -f "$BACKUP/config.tar.gz" ]]; then
      rm -rf -- /etc/xhttp-manager
      tar -C /etc -xzf "$BACKUP/config.tar.gz"
    fi
    if [[ -L "$APP_DIR/app" ]]; then rm "$APP_DIR/app"; fi
    if [[ -L "$APP_DIR/venv" ]]; then rm "$APP_DIR/venv"; fi
    if [[ -n "$OLD_APP" ]]; then ln -s "$OLD_APP" "$APP_DIR/app";
    elif [[ -d "$BACKUP/legacy-app" ]]; then mv "$BACKUP/legacy-app" "$APP_DIR/app"; fi
    if [[ -n "$OLD_VENV" ]]; then ln -s "$OLD_VENV" "$APP_DIR/venv";
    elif [[ -d "$BACKUP/legacy-venv" ]]; then mv "$BACKUP/legacy-venv" "$APP_DIR/venv"; fi
    systemctl daemon-reload
    if (( OLD_PANEL_ENABLED )); then systemctl enable xhttp-manager || true; fi
    if (( OLD_FIREWALL_ENABLED )); then systemctl enable xhttp-manager-firewall || true; fi
    if (( OLD_RUNNING )); then systemctl start xhttp-manager || true; fi
    nginx -t && { systemctl reload nginx || true; }
  fi
  echo "Installation did not complete. Backup: $BACKUP"
  exit "$rc"
}
trap rollback_install ERR
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$RELEASE"
cp -a "$SOURCE/app" "$RELEASE/app"
cp "$SOURCE/requirements.txt" "$RELEASE/requirements.txt"
python3 -m venv "$RELEASE/venv"
"$RELEASE/venv/bin/pip" install --disable-pip-version-check -q -r "$RELEASE/requirements.txt"
chown -R root:root "$RELEASE"
chmod -R go-w "$RELEASE"
if [[ -z "${PANEL_HOSTS:-}" && -f "$ETC_DIR/config.env" ]]; then
  PANEL_HOSTS=$(python3 -c 'from pathlib import Path;print(next((line.split("=",1)[1] for line in Path("/etc/xhttp-manager/config.env").read_text().splitlines() if line.startswith("PANEL_HOSTS=")), ""))')
fi
export PANEL_HOSTS=${PANEL_HOSTS:-$(hostname -I)}
export PANEL_USER=${PANEL_USER:-}
export PANEL_PASS=${PANEL_PASS:-}
export PANEL_PATH=${PANEL_PATH:-}
export PANEL_HTTPS_ONLY=${PANEL_HTTPS_ONLY:-}
nginx -T > "$BACKUP/nginx-before.txt" 2>&1
chmod 0600 "$BACKUP/nginx-before.txt"
python3 - "$BACKUP/nginx-before.txt" <<'PY'
import os,re,sys
hosts=os.environ['PANEL_HOSTS'].split()
if not hosts or any(not re.fullmatch(r'[A-Za-z0-9.:-]+',h) for h in hosts):
    sys.exit('Set PANEL_HOSTS to server IP addresses or an explicit panel hostname.')
for section in re.split(r'# configuration file ',open(sys.argv[1]).read())[1:]:
    filename=section.split(':',1)[0]
    if filename in ('/etc/nginx/conf.d/xhttp-manager.conf', '/etc/nginx/sites-enabled/xhttp-manager.conf') or filename.startswith('/etc/xhttp-manager/nginx-revisions/'):
        continue
    for names in re.findall(r'\bserver_name\s+([^;]+);',section):
        if set(names.split()) & set(hosts):
            sys.exit('An existing nginx site owns a panel IP/hostname. Set PANEL_HOSTS to an unused IP/hostname; existing sites were not modified.')
PY
CHANGED=1
systemctl stop xhttp-manager 2>/dev/null || true
mkdir -p "$ETC_DIR/data" "$ETC_DIR/nginx-revisions" "$ETC_DIR/backups"
if [[ -d "$APP_DIR/app" && ! -L "$APP_DIR/app" ]]; then mv "$APP_DIR/app" "$BACKUP/legacy-app"; fi
if [[ -d "$APP_DIR/venv" && ! -L "$APP_DIR/venv" ]]; then mv "$APP_DIR/venv" "$BACKUP/legacy-venv"; fi
ln -sfn "$RELEASE/app" "$APP_DIR/app"
ln -sfn "$RELEASE/venv" "$APP_DIR/venv"
export XHTTP_MANAGER_DIR="$ETC_DIR"
"$RELEASE/venv/bin/python" - "$BACKUP" <<'PY'
import base64,hashlib,os,re,secrets,sys
from pathlib import Path
etc=Path('/etc/xhttp-manager')
old={}
if (etc/'config.env').exists():
    for line in (etc/'config.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);old[k]=v
user=os.environ.get('PANEL_USER') or old.get('PANEL_USER','admin')
if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',user):
    sys.exit('Invalid panel username')
password=os.environ.get('PANEL_PASS')
oldhash=old.get('PANEL_PASSWORD_HASH')
if not password and not oldhash:
    password=secrets.token_urlsafe(24)
if password:
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000)
    oldhash='pbkdf2_sha256$600000$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(digest).decode()
    secretfile=Path(sys.argv[1])/'new-password.txt'
    secretfile.write_text(password+'\n');secretfile.chmod(0o600)
path=os.environ.get('PANEL_PATH') or old.get('PANEL_PATH','')
if not re.fullmatch(r'/[A-Za-z0-9_-]{24,128}',path):
    path='/'+secrets.token_urlsafe(32)
old.update(PANEL_USER=user,PANEL_PASSWORD_HASH=oldhash,PANEL_PORT='80',PANEL_PATH=path,
    PANEL_HOSTS=os.environ['PANEL_HOSTS'].strip(),XHTTP_MANAGER_DIR=str(etc),
    XHTTP_MANAGER_TRUST_PROXY='1',SESSION_SECRET=(old.get('SESSION_SECRET') if not password else None) or secrets.token_urlsafe(48),
    PANEL_HTTPS_ONLY=os.environ.get('PANEL_HTTPS_ONLY') or old.get('PANEL_HTTPS_ONLY','0'))
for key in list(old):
    if key.startswith('XHTTP_MANAGER_SKIP_') or key == 'XHTTP_MANAGER_ROOT_HELPER':
        old.pop(key)
(etc/'config.env').write_text(''.join(k+'='+v+'\n' for k,v in old.items()))
data=etc/'data/origins.json'
if not data.exists():
    legacy=etc/'origins.json';current=etc/'nginx-revisions/current/origins.json'
    data.write_bytes(current.read_bytes() if current.exists() else legacy.read_bytes() if legacy.exists() else b'[]\n')
PY
chown -R root:"$APP_USER" "$ETC_DIR"
find "$ETC_DIR" -type d -exec chmod 0755 {} +
chmod 0750 "$ETC_DIR/data"
chmod 0700 "$ETC_DIR/backups"
find "$ETC_DIR" -type f -exec chmod 0640 {} +
chmod 0640 "$ETC_DIR/config.env"
touch "$ETC_DIR/data/mutation.lock"
chown "$APP_USER":"$APP_USER" "$ETC_DIR/data/mutation.lock"
chmod 0600 "$ETC_DIR/data/mutation.lock"
cat > /usr/local/sbin/xhttp-manager-nginx <<'EOF'
#!/bin/sh
exec /opt/xhttp-manager/venv/bin/python -I /opt/xhttp-manager/app/nginx_helper.py
EOF
cat > /usr/local/sbin/xhttp-manager-firewall <<'EOF'
#!/bin/sh
exec /opt/xhttp-manager/venv/bin/python -I /opt/xhttp-manager/app/firewall_helper.py "$@"
EOF
chown root:root /usr/local/sbin/xhttp-manager-{nginx,firewall}
chmod 0755 /usr/local/sbin/xhttp-manager-{nginx,firewall}
cat > /etc/sudoers.d/xhttp-manager <<'EOF'
xhttpmgr ALL=(root) NOPASSWD: /usr/local/sbin/xhttp-manager-nginx ""
xhttpmgr ALL=(root) NOPASSWD: /usr/local/sbin/xhttp-manager-firewall status, /usr/local/sbin/xhttp-manager-firewall apply, /usr/local/sbin/xhttp-manager-firewall confirm, /usr/local/sbin/xhttp-manager-firewall cancel
EOF
chmod 0440 /etc/sudoers.d/xhttp-manager
visudo -cf /etc/sudoers.d/xhttp-manager
printf '# Managed by XHTTP Manager\ninclude /etc/xhttp-manager/nginx-revisions/current/*.conf;\n' > /etc/nginx/conf.d/xhttp-manager.conf
if [[ -L /etc/nginx/sites-enabled/xhttp-manager.conf ]]; then rm /etc/nginx/sites-enabled/xhttp-manager.conf; fi
NGINX_DUMP=$(nginx -T 2>&1)
if [[ "$NGINX_DUMP" != *"include /etc/xhttp-manager/nginx-revisions/current/*.conf;"* ]]; then
  mkdir -p /etc/nginx/sites-enabled
  ln -s /etc/nginx/conf.d/xhttp-manager.conf /etc/nginx/sites-enabled/xhttp-manager.conf
  NGINX_DUMP=$(nginx -T 2>&1)
fi
[[ "$NGINX_DUMP" == *"include /etc/xhttp-manager/nginx-revisions/current/*.conf;"* ]] || {
  echo 'nginx does not load conf.d or sites-enabled. Add the managed include explicitly.'
  false
}

"$RELEASE/venv/bin/python" - "$APP_DIR" <<'PY'
import grp,os,sys
from pathlib import Path
for line in Path('/etc/xhttp-manager/config.env').read_text().splitlines():
    if '=' in line:
        k,v=line.split('=',1);os.environ[k]=v
os.environ['XHTTP_MANAGER_ROOT_HELPER']='1'
os.environ['XHTTP_MANAGER_SKIP_NGINX']='0'
os.environ['XHTTP_MANAGER_SKIP_RELOAD']='1'
os.setgid(grp.getgrnam('xhttpmgr').gr_gid)
sys.path.insert(0,sys.argv[1])
from app.main import apply,load_origins,settings,atomic_json,SETTINGS_FILE,write_origins
apply(load_origins())
# Repair compatibility mirrors from the active revision after an interrupted write.
value=settings()
atomic_json(SETTINGS_FILE,value)
write_origins(load_origins())
print('Panel path:',value['panel_path'])
PY
chown root:"$APP_USER" "$ETC_DIR/data/settings.json"
cat > /etc/systemd/system/xhttp-manager.service <<'EOF'
[Unit]
Description=XHTTP Manager
After=network.target nginx.service
[Service]
User=xhttpmgr
Group=www-data
SupplementaryGroups=xhttpmgr
EnvironmentFile=/etc/xhttp-manager/config.env
WorkingDirectory=/opt/xhttp-manager
ExecStart=/opt/xhttp-manager/venv/bin/python -I -m uvicorn app.main:app --app-dir /opt/xhttp-manager --uds /run/xhttp-manager/panel.sock --no-proxy-headers --workers 1
Restart=on-failure
RestartSec=3
RuntimeDirectory=xhttp-manager
RuntimeDirectoryMode=0750
UMask=0007
PrivateTmp=true
ProtectHome=true
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/xhttp-manager-firewall.service <<'EOF'
[Unit]
Description=Restore confirmed XHTTP Manager firewall policy
After=nftables.service
Before=network-pre.target network.target
Wants=network-pre.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/xhttp-manager-firewall restore
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable xhttp-manager xhttp-manager-firewall
systemctl restart xhttp-manager
PANEL_PATH=$("$RELEASE/venv/bin/python" -c 'import json;print(json.load(open("/etc/xhttp-manager/data/settings.json"))["panel_path"])')
HEALTHY=0
for (( attempt=0; attempt<50; attempt++ )); do
  if curl --fail --silent --unix-socket /run/xhttp-manager/panel.sock "http://localhost${PANEL_PATH}/login" >/dev/null; then
    HEALTHY=1
    break
  fi
  sleep .2
done
[[ $HEALTHY -eq 1 ]]

nginx -t
if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
systemctl is-active --quiet xhttp-manager
COMMITTED=1
if (( ACTIVATE_FIREWALL )); then
  if [[ -z "${SSH_CONNECTION:-}" ]]; then
    echo 'Activation skipped: SSH_CONNECTION is missing. Activate from the panel.'
  else
    export XHTTP_FIREWALL_PEER=${SSH_CONNECTION%% *}
    "$RELEASE/venv/bin/python" - <<'PY'
import json,os,subprocess
payload={'policy':{'rules':[]},'peer':os.environ['XHTTP_FIREWALL_PEER']}
result=subprocess.run(['/usr/local/sbin/xhttp-manager-firewall','apply'],input=json.dumps(payload),text=True,capture_output=True)
if result.returncode:
    print('Firewall not activated:',result.stdout or result.stderr)
else:
    print('Firewall armed for 120 seconds. Confirm via the panel, otherwise it will roll back.')
PY
  fi
fi
HOST=${PANEL_HOSTS%% *}
if [[ "$HOST" == *:* ]]; then HOST="[$HOST]"; fi
echo "XHTTP Manager installed. URL: http://${HOST}${PANEL_PATH}"
echo "Credentials preserved on upgrade. Backups: $BACKUP"
if [[ -f "$BACKUP/new-password.txt" ]]; then echo "New password: $BACKUP/new-password.txt (root only)."; fi
echo 'Firewall: activate and confirm in the panel. Host networking is unchanged by default.'
echo 'Use HTTPS or a trusted VPN for administration over untrusted networks.'
