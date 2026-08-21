# XHTTP Manager

Менеджер для добавления доменов, XHTTP-путей и внутренних портов Xray.

Small, nginx-only control panel for routing XHTTP paths to local Xray ports on Ubuntu/Debian.

> **MVP / test release.** Use it on a test server first and keep your existing nginx configuration under version control or backed up.

## What it does

- Installs an isolated FastAPI service managed by systemd.
- Backs up the existing `/etc/nginx` configuration before installing anything.
- Lets you manage origin domains from a web UI.
- Generates one nginx `server` config per origin and tests it with `nginx -t` before reload.
- Keeps timestamped generated-config revisions and supports reverting to a previous revision.

For each origin, set a domain, XHTTP path, local Xray port and optional stub directory. A request to the XHTTP path is proxied to `127.0.0.1:<port>` with buffering and caching disabled; other requests serve the stub or return 404.

## Supported systems

Ubuntu 22.04/24.04 and Debian 12. Run the installer as root:

```bash
git clone https://github.com/ezhikdev/xhttp-manager.git
cd xhttp-manager
sudo bash install.sh
```

The installer asks for panel credentials and port (default `8765`). Press Enter at either credential prompt to generate a strong value. It prints the panel address on completion:

```text
http://SERVER_IP:8765/xhttp-manager
```

## Security notes

- The panel is plain HTTP in this MVP. Put it behind a VPN/firewall, or reverse proxy it with TLS before exposing it publicly.
- Three failed sign-in attempts from one IP block further attempts from that IP for five minutes. These values can be changed with `LOGIN_MAX_ATTEMPTS` and `LOGIN_BLOCK_SECONDS` in `/etc/xhttp-manager/config.env`.
- The installer grants the service user passwordless access only to `nginx -t` and `systemctl reload nginx` so it can safely apply validated changes.
- The XHTTP target is deliberately restricted to localhost and ports `1–65535`.
- `stub root` must be an absolute directory. Ensure the nginx worker can read it.

## Files installed on the server

| Path | Purpose |
| --- | --- |
| `/etc/xhttp-manager/config.env` | Panel settings and password hash |
| `/etc/xhttp-manager/origins.json` | Origin records |
| `/etc/xhttp-manager/nginx-revisions/` | Generated config revisions and the active `current` link |
| `/etc/nginx/conf.d/xhttp-manager.conf` | Stable nginx include installed by the manager |
| `/var/backups/xhttp-manager/` | Pre-install nginx backup |
| `/opt/xhttp-manager/` | Application and virtual environment |

## Operations

```bash
sudo systemctl status xhttp-manager
sudo journalctl -u xhttp-manager -f
sudo systemctl restart xhttp-manager
```

The UI’s **Revert latest change** button restores the previous generated revision, runs `nginx -t`, and reloads nginx only on success. If a generated candidate fails validation, the live revision remains untouched.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
set -a; . ./dev.env; set +a
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

For local development, create `dev.env` from the variables in `install.sh`; set `XHTTP_MANAGER_SKIP_NGINX=1` to skip applying nginx.

Run the automated tests with:

```bash
pip install -r requirements-dev.txt
pytest
```
