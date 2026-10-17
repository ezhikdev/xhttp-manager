"""Root-owned nginx writer; the web account cannot write root-consumed config."""

import fcntl
import grp
import json
import os
import sys
from pathlib import Path


def main():
    if os.geteuid() != 0:
        raise PermissionError("Root helper required")
    os.environ.clear()
    os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    allowed = {
        "XHTTP_MANAGER_DIR",
        "PANEL_HOSTS",
        "PANEL_PATH",
        "PANEL_USER",
        "PANEL_PASSWORD_HASH",
        "SESSION_SECRET",
        "PANEL_HTTPS_ONLY",
    }
    for line in Path("/etc/xhttp-manager/config.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key in allowed:
                os.environ[key] = value
    os.environ["XHTTP_MANAGER_ROOT_HELPER"] = "1"
    os.setgid(grp.getgrnam("xhttpmgr").gr_gid)
    os.umask(0o022)
    sys.path.insert(0, "/opt/xhttp-manager")
    from app import main as app

    text = sys.stdin.read(8 * 1024 * 1024 + 1)
    if len(text) > 8 * 1024 * 1024:
        raise ValueError("Request too large")
    request = json.loads(text)
    if not isinstance(request, dict) or set(request) - {"origins", "panel_path"}:
        raise ValueError("Invalid request")
    items = request["origins"]
    if not isinstance(items, list) or len(items) > 4096:
        raise ValueError("Too many routes")
    items = [app.validate(app.Origin(**item), legacy=True).model_dump() for item in items]
    settings = app.settings()
    if "panel_path" in request:
        settings = {**settings, "panel_path": request["panel_path"]}
    lock = Path("/var/lib/xhttp-manager-config")
    lock.mkdir(mode=0o700, exist_ok=True)
    with (lock / "lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        revision = app.apply(items, settings)
    print(json.dumps({"revision": revision}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": getattr(exc, "detail", str(exc)),
                    "status": getattr(exc, "status_code", 400),
                }
            )
        )
        sys.exit(1)
