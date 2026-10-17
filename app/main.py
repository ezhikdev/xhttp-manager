"""Authenticated administration with atomic, revisioned nginx configuration."""

import base64
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from app.firewall import Policy, render_policy
from app.ui import HTML as PANEL_HTML
from app.ui import LOGIN as LOGIN_HTML

CONFIG_DIR = Path(os.getenv("XHTTP_MANAGER_DIR", "/etc/xhttp-manager"))
DATA_DIR = CONFIG_DIR / "data"
ORIGINS_FILE = DATA_DIR / "origins.json"
REVISIONS = CONFIG_DIR / "nginx-revisions"
CURRENT = REVISIONS / "current"
SETTINGS_FILE = DATA_DIR / "settings.json"
BASE = "/_panel"
USER = os.getenv("PANEL_USER", "admin")
PASS_HASH = os.getenv("PANEL_PASSWORD_HASH", "")
SKIP_NGINX = os.getenv("XHTTP_MANAGER_SKIP_NGINX") == "1"
SKIP_RELOAD = os.getenv("XHTTP_MANAGER_SKIP_RELOAD") == "1"
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)
SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~/@+=:-]+$")
TOKEN_RE = re.compile(r"^/[A-Za-z0-9_-]{24,128}$")
lock = threading.RLock()
login_lock = threading.Lock()
login_attempts = {}
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "3"))
LOGIN_BLOCK_SECONDS = int(os.getenv("LOGIN_BLOCK_SECONDS", "300"))


def atomic_json(path, value, mode=0o640):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            os.chmod(temp, mode)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def mutation():
    with lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with (DATA_DIR / "mutation.lock").open("a") as stream:
            try:
                import fcntl
            except ImportError:
                fcntl = None
            if fcntl:
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def settings():
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        revision_settings = CURRENT / "panel.json"
        if revision_settings.exists():
            value.update(json.loads(revision_settings.read_text(encoding="utf-8")))
        return value
    except FileNotFoundError:
        with mutation():
            if SETTINGS_FILE.exists():
                return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            configured = os.getenv("PANEL_PATH", "")
            value = {
                "panel_path": configured
                if TOKEN_RE.fullmatch(configured)
                else "/" + secrets.token_urlsafe(32),
                "session_secret": secrets.token_urlsafe(48),
            }
            atomic_json(SETTINGS_FILE, value)
            return value


def public_path():
    return settings()["panel_path"]


PANEL_PATH = public_path()


class Origin(BaseModel):
    id: Optional[str] = None
    domain: str = Field(max_length=253)
    path: str = Field(max_length=512)
    port: int = Field(ge=1, le=65535)
    stub_enabled: bool = False
    stub_root: Optional[str] = None
    created_at: Optional[str] = None


class Route(BaseModel):
    path: str = Field(max_length=512)
    port: int = Field(ge=1, le=65535)


class Domain(BaseModel):
    domain: str = Field(max_length=253)
    paths: list[Route] = Field(min_length=1, max_length=128)
    stub_enabled: bool = False
    stub_root: Optional[str] = None


class PathChange(BaseModel):
    path: Optional[str] = None


class Confirmation(BaseModel):
    token: str = Field(min_length=32, max_length=128)


def password_hash(value):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, 600_000)
    return "pbkdf2_sha256$600000$%s$%s" % (
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def valid_password(value):
    try:
        algorithm, rounds, salt, digest = PASS_HASH.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", value.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def authenticated(request):
    return request.session.get("authenticated") is True


def client_ip(request):
    if os.getenv("XHTTP_MANAGER_TRUST_PROXY") == "1":
        try:
            return str(ipaddress.ip_address(request.headers.get("x-real-ip", "")))
        except ValueError:
            return "unknown"
    return request.client.host if request.client else "unknown"


def block_remaining(ip):
    now = time.monotonic()
    with login_lock:
        for key in list(login_attempts):
            if now - login_attempts[key][2] > LOGIN_BLOCK_SECONDS * 2:
                login_attempts.pop(key, None)
        attempt = login_attempts.get(ip)
        return max(0, int(attempt[1] - now + 0.999)) if attempt else 0


def failed_login(ip):
    now = time.monotonic()
    with login_lock:
        count, until, last = login_attempts.get(ip, (0, 0, 0))
        count = 1 if now - last > LOGIN_BLOCK_SECONDS else count + 1
        until = now + LOGIN_BLOCK_SECONDS if count >= LOGIN_MAX_ATTEMPTS else 0
        if len(login_attempts) >= 10000:
            login_attempts.pop(next(iter(login_attempts)))
        login_attempts[ip] = (count, until, now)
        return LOGIN_BLOCK_SECONDS if until else 0


def load_origins():
    source = CURRENT / "origins.json"
    if not source.exists():
        source = ORIGINS_FILE
    try:
        items = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(items, list):
        raise HTTPException(500, "Invalid origins state; restore a backup.")
    for index, item in enumerate(items):
        if not item.get("created_at"):
            item["created_at"] = f"2000-01-01T00:00:00.{index:06d}+00:00"
    return items


def write_origins(items):
    atomic_json(ORIGINS_FILE, items, 0o640)


def validate(origin, legacy=False):
    origin.domain = origin.domain.lower().strip()
    origin.path = origin.path.strip().rstrip("/") or "/"
    if not DOMAIN_RE.fullmatch(origin.domain):
        raise HTTPException(422, "Укажите доменное имя без протокола и порта.")
    if (
        (not SAFE_PATH.fullmatch(origin.path) and not (legacy and origin.path == "/"))
        or "//" in origin.path
        or any(p in (".", "..") for p in origin.path.split("/"))
        or (origin.path == "/" and not legacy)
        or origin.path.startswith("/.xhttp-manager")
    ):
        raise HTTPException(422, "Путь: / и безопасные URL-символы, без %, пробелов и ..")
    if origin.stub_enabled:
        path = origin.stub_root or ""
        if (
            not PurePosixPath(path).is_absolute()
            or not SAFE_PATH.fullmatch(path)
            or any(p in (".", "..") for p in path.split("/"))
        ):
            raise HTTPException(422, "Укажите безопасный абсолютный каталог заглушки.")
    else:
        origin.stub_root = None
    return origin


def sync_domain_stub(items, domain, enabled, root):
    for item in items:
        if item["domain"] == domain:
            item.update(stub_enabled=enabled, stub_root=root if enabled else None)


def upstream_name(port):
    return f"xhttp_manager_xray_{port}"


def render_upstreams(ports):
    return (
        "\n\n".join(
            f"""upstream {upstream_name(port)} {{
    server 127.0.0.1:{port};
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 30s;
}}"""
            for port in sorted(ports)
        )
        + "\n"
    )


def render_route(origin, upstream):
    path = origin["path"].rstrip("/") or "/"
    directives = f"""        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        proxy_max_temp_file_size 0;
        client_max_body_size 0;
        gzip off;
        proxy_connect_timeout 5s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
        send_timeout 3600s;
        add_header Cache-Control "no-store" always;
        add_header X-Accel-Buffering "no" always;"""
    if path == "/":
        return f"    location ^~ / {{\n{directives}\n    }}"
    return f"    location = {path} {{\n{directives}\n    }}\n    location ^~ {path}/ {{\n{directives}\n    }}"


def render_domain(domain, routes):
    ordered = sorted(routes, key=lambda r: r["path"])
    locations = "\n\n".join(render_route(r, upstream_name(r["port"])) for r in ordered)
    first = ordered[0]
    fallback = (
        f"    location / {{\n        root {first['stub_root']};\n        try_files $uri $uri/ /index.html;\n    }}"
        if first["stub_enabled"]
        else "    location / { return 404; }"
    )
    if any(r["path"] == "/" for r in routes):
        fallback = ""
    return f"""# Managed by XHTTP Manager
server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
    keepalive_timeout 30s;
{locations}
{fallback}
}}
"""


def render_panel(value):
    path = value["panel_path"]
    if not TOKEN_RE.fullmatch(path):
        raise HTTPException(422, "Invalid panel path")
    hosts = os.getenv("PANEL_HOSTS", "127.0.0.1").split()
    if not hosts or any(not re.fullmatch(r"[a-zA-Z0-9.:-]+", host) for host in hosts):
        raise HTTPException(422, "Invalid PANEL_HOSTS")
    proxy = """        proxy_pass http://unix:/run/xhttp-manager/panel.sock;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For "";
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        client_max_body_size 128k;
        proxy_read_timeout 45s;"""
    return f"""# Managed by XHTTP Manager: no default_server takeover.
server {{
    listen 80;
    listen [::]:80;
    server_name {" ".join(hosts)};
    keepalive_timeout 0;
    location = {path} {{
{proxy}
    }}
    location ^~ {path}/ {{
{proxy}
    }}
    location / {{ return 404; }}
}}
"""


def run_nginx(args):
    try:
        result = subprocess.run(
            ([] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo", "-n"]) + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, "nginx unavailable or timed out.") from exc
    if result.returncode or "conflicting server name" in result.stderr:
        raise HTTPException(400, "nginx: " + (result.stderr or result.stdout)[-1500:])


def switch_revision(target):
    temp = REVISIONS / ("link-" + secrets.token_hex(6))
    temp.symlink_to(target)
    os.replace(temp, CURRENT)


def apply(items, panel_settings=None):
    if not SKIP_NGINX and os.getenv("XHTTP_MANAGER_ROOT_HELPER") != "1":
        payload = {"origins": items}
        if panel_settings:
            payload["panel_path"] = panel_settings["panel_path"]
        try:
            result = subprocess.run(
                ["sudo", "-n", "/usr/local/sbin/xhttp-manager-nginx"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(503, "nginx helper unavailable or timed out.") from exc
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise HTTPException(503, "Invalid nginx helper response.")
        if result.returncode:
            raise HTTPException(
                value.get("status", 400), value.get("error", "nginx rejected change")
            )
        return value["revision"]
    if not SKIP_NGINX and (not hasattr(os, "geteuid") or os.geteuid() != 0):
        raise HTTPException(403, "Root helper required")
    return _apply(items, panel_settings)


def _apply(items, panel_settings=None):
    REVISIONS.mkdir(parents=True, exist_ok=True)
    candidate = REVISIONS / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + secrets.token_hex(3)
    )
    candidate.mkdir()
    previous = CURRENT.resolve() if CURRENT.is_symlink() else None
    old_settings = settings()
    value = panel_settings or old_settings
    try:
        grouped, keys = {}, set()
        for item in items:
            normalized = validate(Origin(**item), legacy=True)
            # Never interpolate unvalidated strings, including old files.
            safe = normalized.model_dump()
            key = (safe["domain"], safe["path"])
            if key in keys:
                raise HTTPException(409, "Этот домен уже использует такой путь.")
            keys.add(key)
            grouped.setdefault(safe["domain"], []).append(safe)
        if set(grouped) & set(os.getenv("PANEL_HOSTS", "127.0.0.1").lower().split()):
            raise HTTPException(409, "This hostname is reserved for panel access.")
        if items:
            (candidate / "000-upstreams.conf").write_text(
                render_upstreams({r["port"] for r in items}), encoding="utf-8"
            )
        (candidate / "001-panel.conf").write_text(render_panel(value), encoding="utf-8")
        for domain, routes in grouped.items():
            name = hashlib.sha256(domain.encode()).hexdigest()[:16]
            (candidate / (name + ".conf")).write_text(
                render_domain(domain, routes), encoding="utf-8"
            )
        atomic_json(candidate / "origins.json", items, 0o640)
        atomic_json(candidate / "panel.json", {"panel_path": value["panel_path"]}, 0o640)
        same = previous and {p.name: p.read_bytes() for p in candidate.glob("*.conf")} == {
            p.name: p.read_bytes() for p in previous.glob("*.conf")
        }
        if same and items == load_origins():
            shutil.rmtree(candidate)
            return previous.name
        switch_revision(candidate)
        if not SKIP_NGINX:
            run_nginx(["nginx", "-t"])
        if value != old_settings:
            atomic_json(SETTINGS_FILE, value)
        if not SKIP_NGINX and not SKIP_RELOAD:
            run_nginx(["systemctl", "reload", "nginx"])
        write_origins(items)
    except Exception:
        if previous:
            switch_revision(previous)
        else:
            CURRENT.unlink(missing_ok=True)
        if value != old_settings:
            atomic_json(SETTINGS_FILE, old_settings)
        if not SKIP_NGINX and not SKIP_RELOAD and previous:
            with contextlib.suppress(HTTPException):
                run_nginx(["systemctl", "reload", "nginx"])
        shutil.rmtree(candidate, ignore_errors=True)
        raise
    history = sorted(
        p
        for p in REVISIONS.iterdir()
        if p.is_dir()
        and not p.is_symlink()
        and p.name != "initial"
        and (p / "origins.json").exists()
    )
    for stale in history[:-30]:
        if stale not in (candidate, previous):
            shutil.rmtree(stale, ignore_errors=True)
    return candidate.name


def grouped_domains(items):
    groups = {}
    for item in items:
        name = item["domain"]
        groups.setdefault(
            name,
            {
                "domain": name,
                "paths": [],
                "stub_enabled": item["stub_enabled"],
                "stub_root": item.get("stub_root"),
                "created_at": item["created_at"],
            },
        )
        groups[name]["paths"].append({"path": item["path"], "port": item["port"]})
    return list(groups.values())


app = FastAPI(title="XHTTP Manager", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def perimeter(request: Request, call_next):
    if os.getenv("XHTTP_MANAGER_TRUST_PROXY") == "1":
        scheme = request.headers.get("x-forwarded-proto")
        if scheme in ("http", "https"):
            request.scope["scheme"] = scheme
    path = public_path()
    incoming = request.scope["path"]
    if incoming != path and not incoming.startswith(path + "/"):
        return HTMLResponse("Not found", 404)
    request.scope["path"] = BASE + incoming[len(path) :]
    request.scope["raw_path"] = request.scope["path"].encode()
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        chunks, length = [], 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > 131072:
                return HTMLResponse("Request too large", 413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
            return HTMLResponse("Cross-origin request rejected", 403)
    response = await call_next(request)
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "Referrer-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        }
    )
    return response


def csrf(request):
    return request.session.setdefault("csrf", secrets.token_urlsafe(32))


def require(request, changing=False):
    if not authenticated(request):
        raise HTTPException(401, "Требуется вход.")
    if changing and not hmac.compare_digest(
        request.headers.get("x-csrf-token", "").encode(), csrf(request).encode()
    ):
        raise HTTPException(403, "Обновите страницу: неверный CSRF-токен.")


def render_html(template, request, error=""):
    return (
        template.replace("__PATH__", public_path())
        .replace("__CSRF__", csrf(request))
        .replace("<!--ERROR-->", error)
    )


@app.get(BASE, response_class=HTMLResponse)
def page(request: Request):
    if not authenticated(request):
        return RedirectResponse(public_path() + "/login", 303)
    return HTMLResponse(render_html(PANEL_HTML, request))


@app.get(BASE + "/")
def trailing():
    return RedirectResponse(public_path(), 303)


@app.get(BASE + "/login", response_class=HTMLResponse)
def login_page(request: Request):
    return HTMLResponse(render_html(LOGIN_HTML, request))


@app.post(BASE + "/login")
async def login(request: Request):
    ip = client_ip(request)
    remaining = block_remaining(ip)
    if remaining:
        return HTMLResponse(
            render_html(
                LOGIN_HTML, request, f'<p class="error">Повторите через {remaining} сек.</p>'
            ),
            429,
            headers={"Retry-After": str(remaining)},
        )
    data = await request.form()
    if not hmac.compare_digest(str(data.get("csrf", "")).encode(), csrf(request).encode()):
        raise HTTPException(403, "Обновите страницу входа.")
    user_ok = hmac.compare_digest(str(data.get("username", "")).encode(), USER.encode())
    password_ok = valid_password(str(data.get("password", "")))
    if user_ok and password_ok:
        with login_lock:
            login_attempts.pop(ip, None)
        request.session.clear()
        request.session.update(authenticated=True, csrf=secrets.token_urlsafe(32))
        return RedirectResponse(public_path(), 303)
    remaining = failed_login(ip)
    return HTMLResponse(
        render_html(LOGIN_HTML, request, '<p class="error">Неверный логин или пароль.</p>'),
        429 if remaining else 401,
        headers={"Retry-After": str(remaining)} if remaining else {},
    )


@app.post(BASE + "/logout")
async def logout(request: Request):
    data = await request.form()
    if not hmac.compare_digest(str(data.get("csrf", "")).encode(), csrf(request).encode()):
        raise HTTPException(403, "Invalid CSRF token")
    request.session.clear()
    return RedirectResponse(public_path() + "/login", 303)


@app.get(BASE + "/api/origins")
def list_origins(request: Request):
    require(request)
    return load_origins()


@app.post(BASE + "/api/origins")
def create(origin: Origin, request: Request):
    require(request, True)
    with mutation():
        items = load_origins()
        origin.domain = origin.domain.strip().lower()
        shared = next((i for i in items if i["domain"] == origin.domain), None)
        if shared and not ({"stub_enabled", "stub_root"} & origin.model_fields_set):
            origin.stub_enabled, origin.stub_root = shared["stub_enabled"], shared.get("stub_root")
        data = validate(origin).model_dump()
        data.update(id=secrets.token_hex(8), created_at=datetime.now(timezone.utc).isoformat())
        items.append(data)
        sync_domain_stub(items, data["domain"], data["stub_enabled"], data.get("stub_root"))
        apply(items)
        return data


@app.put(BASE + "/api/origins/{origin_id}")
def update(origin_id: str, origin: Origin, request: Request):
    require(request, True)
    with mutation():
        items = load_origins()
        existing = next((i for i in items if i["id"] == origin_id), None)
        if not existing:
            raise HTTPException(404, "Origin не найден.")
        origin.domain = origin.domain.strip().lower()
        shared = next((i for i in items if i["domain"] == origin.domain), None)
        if shared and not ({"stub_enabled", "stub_root"} & origin.model_fields_set):
            origin.stub_enabled, origin.stub_root = shared["stub_enabled"], shared.get("stub_root")
        data = validate(origin).model_dump()
        data.update(id=origin_id, created_at=existing["created_at"])
        items = [data if i["id"] == origin_id else i for i in items]
        sync_domain_stub(items, data["domain"], data["stub_enabled"], data.get("stub_root"))
        apply(items)
        return data


@app.delete(BASE + "/api/origins/{origin_id}")
def delete(origin_id: str, request: Request):
    require(request, True)
    with mutation():
        items = load_origins()
        new = [i for i in items if i["id"] != origin_id]
        if len(items) == len(new):
            raise HTTPException(404, "Origin не найден.")
        apply(new)
        return {"ok": True}


@app.get(BASE + "/api/domains")
def list_domains(request: Request):
    require(request)
    return grouped_domains(load_origins())


def save_domain(domain, previous=None):
    with mutation():
        items = load_origins()
        name = domain.domain.strip().lower()
        if any(i["domain"] == name and i["domain"] != previous for i in items):
            raise HTTPException(409, "Домен уже существует; отредактируйте его.")
        if previous and not any(i["domain"] == previous for i in items):
            raise HTTPException(404, "Домен не найден.")
        old = {i["path"]: i for i in items if i["domain"] == previous}
        replacement = []
        for route in domain.paths:
            item = validate(
                Origin(
                    domain=name,
                    path=route.path,
                    port=route.port,
                    stub_enabled=domain.stub_enabled,
                    stub_root=domain.stub_root,
                ),
                legacy=route.path == "/" and "/" in old,
            ).model_dump()
            existing = old.get(item["path"], {})
            item.update(
                id=existing.get("id", secrets.token_hex(8)),
                created_at=existing.get("created_at", datetime.now(timezone.utc).isoformat()),
            )
            replacement.append(item)
        apply([i for i in items if i["domain"] != previous] + replacement)
        return grouped_domains(replacement)[0]


@app.post(BASE + "/api/domains")
def add_domain(domain: Domain, request: Request):
    require(request, True)
    return save_domain(domain)


@app.put(BASE + "/api/domains/{name}")
def edit_domain(name: str, domain: Domain, request: Request):
    require(request, True)
    return save_domain(domain, name)


@app.delete(BASE + "/api/domains/{name}")
def remove_domain(name: str, request: Request):
    require(request, True)
    with mutation():
        items = load_origins()
        new = [i for i in items if i["domain"] != name]
        if len(new) == len(items):
            raise HTTPException(404, "Домен не найден.")
        apply(new)
        return {"ok": True}


@app.post(BASE + "/api/rollback")
def rollback(request: Request):
    require(request, True)
    with mutation():
        current = CURRENT.resolve()
        revisions = sorted(
            (
                p
                for p in REVISIONS.iterdir()
                if p.is_dir() and not p.is_symlink() and (p / "origins.json").exists()
            ),
            key=lambda p: "0" if p.name == "initial" else p.name,
        )
        index = revisions.index(current)
        if index == 0:
            raise HTTPException(400, "Предыдущей ревизии нет.")
        target = revisions[index - 1]
        return {
            "ok": True,
            "revision": apply(json.loads((target / "origins.json").read_text(encoding="utf-8"))),
        }


@app.get(BASE + "/api/settings")
def get_settings(request: Request):
    require(request)
    return {
        "panel_path": public_path(),
        "user": USER,
        "secure_cookie": os.getenv("PANEL_HTTPS_ONLY") == "1",
    }


@app.put(BASE + "/api/settings/path")
def rotate_path(change: PathChange, request: Request):
    require(request, True)
    with mutation():
        path = change.path or "/" + secrets.token_urlsafe(32)
        if not TOKEN_RE.fullmatch(path):
            raise HTTPException(422, "Путь: / и 24–128 символов A–Z, a–z, 0–9, _ или -.")
        apply(load_origins(), {**settings(), "panel_path": path})
        return {"panel_path": path}


def firewall_call(action, **payload):
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/xhttp-manager-firewall", action],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=40,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, "Firewall helper недоступен; проверьте установку.") from exc
    if result.returncode:
        raise HTTPException(400, (result.stdout or result.stderr)[-1500:])
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise HTTPException(503, "Некорректный ответ Firewall helper.") from exc


@app.get(BASE + "/api/firewall")
def firewall_status(request: Request):
    require(request)
    return firewall_call("status")


@app.post(BASE + "/api/firewall/preview")
def firewall_preview(policy: Policy, request: Request):
    require(request, True)
    return {"ruleset": render_policy(policy), "policy": policy.model_dump()}


@app.put(BASE + "/api/firewall")
def firewall_apply(policy: Policy, request: Request):
    require(request, True)
    return firewall_call("apply", policy=policy.model_dump(), peer=client_ip(request))


@app.post(BASE + "/api/firewall/confirm")
def firewall_confirm(confirmation: Confirmation, request: Request):
    require(request, True)
    return firewall_call("confirm", token=confirmation.token, peer=client_ip(request))


@app.post(BASE + "/api/firewall/cancel")
def firewall_cancel(request: Request):
    require(request, True)
    return firewall_call("cancel")


@app.get(BASE + "/api/system")
def system_status(request: Request):
    require(request)
    origins = load_origins()
    disk = shutil.disk_usage(CONFIG_DIR)
    return {
        "domains": len({i["domain"] for i in origins}),
        "paths": len(origins),
        "revision": CURRENT.resolve().name if CURRENT.is_symlink() else None,
        "load": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
        "disk_free": disk.free,
        "disk_total": disk.total,
        "nginx_validation": not SKIP_NGINX,
        "panel_port": 80,
        "backend": "unix socket",
        "firewall_defaults": [22, 80, 443, 2222],
    }


app.mount(BASE + "/assets", StaticFiles(directory=Path(__file__).parent / "static"), name="assets")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET") or settings()["session_secret"],
    session_cookie="xhttp_session",
    max_age=8 * 3600,
    https_only=os.getenv("PANEL_HTTPS_ONLY") == "1",
    same_site="strict",
)
