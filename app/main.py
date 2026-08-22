import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.ui import HTML as PANEL_HTML, LOGIN as LOGIN_HTML

CONFIG_DIR = Path(os.getenv("XHTTP_MANAGER_DIR", "/etc/xhttp-manager"))
DATA_DIR = CONFIG_DIR / "data"
ORIGINS_FILE = DATA_DIR / "origins.json"
REVISIONS = CONFIG_DIR / "nginx-revisions"
CURRENT = REVISIONS / "current"
ERROR_PAGE_URI = "/.xhttp-manager/errors/404.html"
ERROR_PAGE_FILE = "/opt/xhttp-manager/app/static/404.html"
PANEL_PATH = os.getenv("PANEL_PATH", "/xhttp-manager").rstrip("/") or "/xhttp-manager"
USER = os.getenv("PANEL_USER", "admin")
PASS_HASH = os.getenv("PANEL_PASSWORD_HASH", "")
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "3"))
LOGIN_BLOCK_SECONDS = int(os.getenv("LOGIN_BLOCK_SECONDS", "300"))
SKIP_NGINX = os.getenv("XHTTP_MANAGER_SKIP_NGINX") == "1"
SKIP_RELOAD = os.getenv("XHTTP_MANAGER_SKIP_RELOAD") == "1"
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$")
SAFE_NGINX_PATH_RE = re.compile(r"^/[A-Za-z0-9._~%/@+=:-]*$")

app = FastAPI(title="XHTTP Manager", docs_url=None, redoc_url=None)
login_attempts = {}
login_attempts_lock = threading.Lock()

class Origin(BaseModel):
    id: Optional[str] = None
    domain: str = Field(max_length=253)
    path: str = Field(max_length=512)
    port: int = Field(ge=1, le=65535)
    stub_enabled: bool = True
    stub_root: Optional[str] = None
    created_at: Optional[str] = None

def password_hash(value: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, 210_000)
    return "pbkdf2_sha256$210000$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(digest).decode())

def valid_password(value: str) -> bool:
    try:
        _, rounds, salt, digest = PASS_HASH.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", value.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except ValueError:
        return False

def authenticated(request: Request) -> bool:
    return request.session.get("authenticated") is True

def client_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For by default: the panel is exposed directly in this MVP.
    return request.client.host if request.client else "unknown"

def block_remaining(ip: str) -> int:
    now = time.monotonic()
    with login_attempts_lock:
        attempt = login_attempts.get(ip)
        if not attempt:
            return 0
        _, blocked_until, last_attempt = attempt
        if blocked_until > now:
            return max(1, int(blocked_until - now + 0.999))
        if blocked_until or now - last_attempt > LOGIN_BLOCK_SECONDS:
            login_attempts.pop(ip, None)
        return 0

def record_failed_login(ip: str) -> int:
    now = time.monotonic()
    with login_attempts_lock:
        count, blocked_until, last_attempt = login_attempts.get(ip, (0, 0.0, 0.0))
        if blocked_until > now:
            return max(1, int(blocked_until - now + 0.999))
        if now - last_attempt > LOGIN_BLOCK_SECONDS:
            count = 0
        count += 1
        if count >= LOGIN_MAX_ATTEMPTS:
            blocked_until = now + LOGIN_BLOCK_SECONDS
            login_attempts[ip] = (count, blocked_until, now)
            return LOGIN_BLOCK_SECONDS
        login_attempts[ip] = (count, 0.0, now)
        return 0

def clear_failed_logins(ip: str):
    with login_attempts_lock:
        login_attempts.pop(ip, None)

def load_origins():
    try:
        items = json.loads(ORIGINS_FILE.read_text())
    except FileNotFoundError:
        return []
    legacy_base = datetime(2000, 1, 1, tzinfo=timezone.utc)
    for index, item in enumerate(items):
        if not item.get("created_at"):
            created = legacy_base + timedelta(seconds=index)
            item["created_at"] = created.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return items

def created_at_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

def sync_domain_stub(items, domain, stub_enabled, stub_root):
    for item in items:
        if item["domain"] == domain:
            item["stub_enabled"] = stub_enabled
            item["stub_root"] = stub_root if stub_enabled else None
def write_origins(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = ORIGINS_FILE.with_suffix(".new")
    try:
        temp.write_text(json.dumps(items, indent=2) + "\n")
        temp.replace(ORIGINS_FILE)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Не удалось сохранить origin. Проверьте права каталога данных.",
        ) from exc

def validate(origin: Origin):
    origin.domain = origin.domain.lower().strip()
    origin.path = origin.path.strip()
    if not DOMAIN_RE.match(origin.domain): raise HTTPException(422, "Enter a valid hostname, without scheme or port.")
    if not SAFE_NGINX_PATH_RE.match(origin.path) or ".." in origin.path:
        raise HTTPException(422, "Path must start with / and use only safe URL characters.")
    if origin.path == ERROR_PAGE_URI:
        raise HTTPException(422, "This path is reserved by XHTTP Manager.")
    if origin.stub_enabled:
        if not origin.stub_root or not PurePosixPath(origin.stub_root).is_absolute() or not SAFE_NGINX_PATH_RE.match(origin.stub_root):
            raise HTTPException(422, "Stub root must be a safe absolute directory when stub is enabled.")
    return origin

def render_route(origin, upstream_name):
    return f'''    # XHTTP route: {origin['id']}
    location ^~ {origin['path']} {{
        proxy_pass http://{upstream_name};
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
        gzip off;
        proxy_connect_timeout 5s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
        send_timeout 3600s;
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
        add_header X-Accel-Buffering "no" always;
    }}'''


def upstream_name(port):
    return f"xhttp_manager_xray_{port}"


def render_upstreams(ports):
    return "\n\n".join(
        f'''upstream {upstream_name(port)} {{
    server 127.0.0.1:{port};
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 30s;
}}'''
        for port in sorted(ports)
    ) + "\n"


def render_domain(domain, routes):
    ordered = sorted(routes, key=lambda item: (item["path"], item["id"]))
    stub_enabled = ordered[0]["stub_enabled"]
    stub_root = ordered[0]["stub_root"]
    locations = "\n\n".join(
        render_route(item, upstream_name(item["port"]))
        for item in ordered
    )
    fallback = (
        f'''    location / {{
        root {stub_root};
        try_files $uri $uri/ /index.html;
    }}'''
        if stub_enabled
        else '''    location / {
        return 404;
    }'''
    )
    route_ids = ", ".join(item["id"] for item in ordered)
    return f'''# Managed by XHTTP Manager. Route IDs: {route_ids}

server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
    keepalive_timeout 30s;

{locations}

{fallback}
}}
'''


def generated_config_matches(candidate):
    if not CURRENT.is_symlink():
        return False
    try:
        current = CURRENT.resolve(strict=True)
        candidate_files = {path.name: path.read_bytes() for path in candidate.glob("*.conf")}
        current_files = {path.name: path.read_bytes() for path in current.glob("*.conf")}
        return candidate_files == current_files
    except OSError:
        return False

def previous_revision(revisions, current_name):
    ordered = sorted((p for p in revisions if p.name != "initial"), key=lambda p: p.name)
    initial = next((p for p in revisions if p.name == "initial"), None)
    if initial:
        ordered.insert(0, initial)
    names = [p.name for p in ordered]
    if current_name not in names:
        raise HTTPException(400, "Current revision is not available.")
    index = names.index(current_name)
    if index == 0:
        raise HTTPException(400, "No previous revision available.")
    return ordered[index - 1]

def apply(items):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    candidate = REVISIONS / stamp
    candidate.mkdir(parents=True)
    grouped = {}
    for item in items:
        grouped.setdefault(item["domain"], []).append(item)
    ports = {item["port"] for item in items}
    if ports:
        (candidate / "000-upstreams.conf").write_text(render_upstreams(ports))
    for domain in sorted(grouped):
        config_id = hashlib.sha256(domain.encode()).hexdigest()[:16]
        (candidate / f"{config_id}.conf").write_text(render_domain(domain, grouped[domain]))
    (candidate / "origins.json").write_text(json.dumps(items, indent=2) + "\n")
    if generated_config_matches(candidate):
        current_name = Path(os.readlink(CURRENT)).name
        shutil.rmtree(candidate)
        return current_name
    previous = os.readlink(CURRENT) if CURRENT.is_symlink() else None
    if not SKIP_NGINX:
        if CURRENT.exists() or CURRENT.is_symlink(): CURRENT.unlink()
        CURRENT.symlink_to(candidate)
        checked = subprocess.run(["sudo", "nginx", "-t"], text=True, capture_output=True)
        if checked.returncode:
            CURRENT.unlink(missing_ok=True)
            if previous: CURRENT.symlink_to(previous)
            shutil.rmtree(candidate)
            raise HTTPException(400, "nginx rejected this change: " + (checked.stderr or checked.stdout)[-1200:])
        if not SKIP_RELOAD:
            reloaded = subprocess.run(["sudo", "systemctl", "reload", "nginx"], text=True, capture_output=True)
            if reloaded.returncode:
                CURRENT.unlink(missing_ok=True)
                if previous: CURRENT.symlink_to(previous)
                shutil.rmtree(candidate)
                raise HTTPException(500, "nginx validated but reload failed; previous revision was restored: " + (reloaded.stderr or reloaded.stdout)[-1200:])
    return stamp

from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", PASS_HASH or secrets.token_urlsafe(32)), https_only=False, same_site="lax")

@app.get(PANEL_PATH, response_class=HTMLResponse)
def page(request: Request):
    if not authenticated(request): return RedirectResponse(PANEL_PATH + "/login")
    return HTMLResponse(PANEL_HTML.replace("__PATH__", PANEL_PATH))

@app.get(PANEL_PATH + "/login", response_class=HTMLResponse)
def login_page(): return HTMLResponse(LOGIN_HTML.replace("__PATH__", PANEL_PATH))

@app.post(PANEL_PATH + "/login")
async def login(request: Request):
    ip = client_ip(request)
    remaining = block_remaining(ip)
    if remaining:
        return HTMLResponse(
            LOGIN_HTML.replace("__PATH__", PANEL_PATH).replace("<!--ERROR-->", f"<p class='error'>Слишком много попыток. Повторите через {remaining} сек.</p>"),
            status_code=429,
            headers={"Retry-After": str(remaining)},
        )
    data = await request.form()
    user_ok = hmac.compare_digest(str(data.get("username", "")), USER)
    password_ok = valid_password(str(data.get("password", "")))
    if user_ok and password_ok:
        clear_failed_logins(ip)
        request.session["authenticated"] = True
        return RedirectResponse(PANEL_PATH, status_code=303)
    remaining = record_failed_login(ip)
    message = f"Слишком много попыток. Повторите через {remaining} сек." if remaining else "Неверный логин или пароль."
    status = 429 if remaining else 401
    headers = {"Retry-After": str(remaining)} if remaining else None
    return HTMLResponse(LOGIN_HTML.replace("__PATH__", PANEL_PATH).replace("<!--ERROR-->", f"<p class='error'>{message}</p>"), status, headers=headers)

@app.post(PANEL_PATH + "/logout")
def logout(request: Request): request.session.clear(); return RedirectResponse(PANEL_PATH + "/login", 303)

def require(request):
    if not authenticated(request): raise HTTPException(401, "Sign in required")

@app.get(PANEL_PATH + "/api/origins")
def list_origins(request: Request): require(request); return load_origins()

@app.post(PANEL_PATH + "/api/origins")
def create(origin: Origin, request: Request):
    require(request)
    items = load_origins()
    origin.domain = origin.domain.lower().strip()
    shared = next((item for item in items if item["domain"] == origin.domain), None)
    if shared and not ({"stub_enabled", "stub_root"} & origin.model_fields_set):
        origin.stub_enabled = shared["stub_enabled"]
        origin.stub_root = shared.get("stub_root")
    origin = validate(origin)
    if any(item["domain"] == origin.domain and item["path"] == origin.path for item in items):
        raise HTTPException(409, "Этот домен уже использует такой XHTTP-путь.")
    data = origin.model_dump(exclude={"created_at"})
    data["id"] = secrets.token_hex(8)
    data["created_at"] = created_at_now()
    items.append(data)
    sync_domain_stub(items, data["domain"], data["stub_enabled"], data.get("stub_root"))
    apply(items)
    write_origins(items)
    return data

@app.put(PANEL_PATH + "/api/origins/{origin_id}")
def update(origin_id: str, origin: Origin, request: Request):
    require(request)
    items = load_origins()
    existing = next((item for item in items if item["id"] == origin_id), None)
    if not existing:
        raise HTTPException(404, "Origin не найден.")
    origin.domain = origin.domain.lower().strip()
    shared = next((item for item in items if item["domain"] == origin.domain and item["id"] != origin_id), None)
    if shared and not ({"stub_enabled", "stub_root"} & origin.model_fields_set):
        origin.stub_enabled = shared["stub_enabled"]
        origin.stub_root = shared.get("stub_root")
    origin = validate(origin)
    if any(item["domain"] == origin.domain and item["path"] == origin.path and item["id"] != origin_id for item in items):
        raise HTTPException(409, "Этот домен уже использует такой XHTTP-путь.")
    data = origin.model_dump(exclude={"created_at"})
    data["id"] = origin_id
    data["created_at"] = existing["created_at"]
    items = [data if item["id"] == origin_id else item for item in items]
    sync_domain_stub(items, data["domain"], data["stub_enabled"], data.get("stub_root"))
    apply(items)
    write_origins(items)
    return data
@app.delete(PANEL_PATH + "/api/origins/{origin_id}")
def delete(origin_id: str, request: Request):
    require(request); items = load_origins(); new = [x for x in items if x['id'] != origin_id]
    if len(new) == len(items): raise HTTPException(404, "Origin not found")
    apply(new); write_origins(new); return {"ok": True}

@app.post(PANEL_PATH + "/api/rollback")
def rollback(request: Request):
    require(request); revisions = [p for p in REVISIONS.iterdir() if p.is_dir() and not p.is_symlink()]
    current = Path(os.readlink(CURRENT)).name if CURRENT.is_symlink() else ""
    target = previous_revision(revisions, current); previous = os.readlink(CURRENT)
    CURRENT.unlink(); CURRENT.symlink_to(target)
    if not SKIP_NGINX:
        check = subprocess.run(["sudo", "nginx", "-t"], text=True, capture_output=True)
        if check.returncode: CURRENT.unlink(); CURRENT.symlink_to(previous); raise HTTPException(400, "Rollback config failed nginx validation.")
        reload_result = subprocess.run(["sudo", "systemctl", "reload", "nginx"], text=True, capture_output=True)
        if reload_result.returncode:
            CURRENT.unlink(); CURRENT.symlink_to(previous)
            raise HTTPException(500, "nginx reload failed; previous revision was restored.")
    state = target / "origins.json"
    if state.exists(): write_origins(json.loads(state.read_text()))
    return {"ok": True, "revision": target.name}

LOGIN = '''<!doctype html><meta name="viewport" content="width=device-width"><style>body{font:16px system-ui;max-width:360px;margin:12vh auto;padding:20px}input,button{box-sizing:border-box;width:100%;padding:10px;margin:6px 0}.error{color:#b00}</style><h1>XHTTP Manager</h1><!--ERROR--><form method="post" action="__PATH__/login"><input name="username" placeholder="Login" required autofocus><input name="password" type="password" placeholder="Password" required><button>Sign in</button></form>'''
HTML = '''<!doctype html><meta name="viewport" content="width=device-width"><style>body{font:16px system-ui;max-width:1000px;margin:auto;padding:20px}input{padding:8px;margin:3px;width:180px}button{padding:8px;margin:3px}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}.error{color:#b00;white-space:pre-wrap}</style><h1>XHTTP Manager</h1><p>Create or edit an origin. Changes are tested with nginx before they are activated.</p><form id=f><input name=domain placeholder="origin.example.com" required><input name=path value="/xhttp" required><input name=port type=number value=10086 required><label><input name=stub_enabled type=checkbox checked> stub</label><input name=stub_root placeholder="/var/www/stub"><button id=save>Save origin</button><button type=button onclick="clearForm()">Cancel edit</button></form><p id=m class=error></p><button onclick="rollback()">Revert latest change</button><form method=post action="__PATH__/logout" style="display:inline"><button>Sign out</button></form><table><thead><tr><th>Domain</th><th>XHTTP path</th><th>Port</th><th>Stub</th><th></th></tr></thead><tbody id=rows></tbody></table><script>const P='__PATH__',msg=x=>m.textContent=x;let data=[],editing=null;async function api(u,o={}){let r=await fetch(P+'/api/'+u,o),t=await r.text();if(!r.ok)throw Error(t);return t&&JSON.parse(t)}async function load(){data=await api('origins');rows.innerHTML=data.map(x=>`<tr><td>${x.domain}</td><td>${x.path}</td><td>${x.port}</td><td>${x.stub_enabled?x.stub_root:'off'}</td><td><button onclick="edit('${x.id}')">Edit</button><button onclick="del('${x.id}')">Delete</button></td></tr>`).join('')}function edit(id){let x=data.find(x=>x.id===id);editing=id;f.domain.value=x.domain;f.path.value=x.path;f.port.value=x.port;f.stub_enabled.checked=x.stub_enabled;f.stub_root.value=x.stub_root||'';save.textContent='Update origin'}function clearForm(){editing=null;f.reset();f.path.value='/xhttp';f.port.value=10086;f.stub_enabled.checked=true;save.textContent='Save origin'}f.onsubmit=async e=>{e.preventDefault();msg('');let x=Object.fromEntries(new FormData(f));x.port=+x.port;x.stub_enabled=f.stub_enabled.checked;try{await api('origins'+(editing?'/'+editing:''),{method:editing?'PUT':'POST',headers:{'content-type':'application/json'},body:JSON.stringify(x)});clearForm();load()}catch(e){msg(e.message)}};async function del(id){if(confirm('Delete this origin?'))try{await api('origins/'+id,{method:'DELETE'});load()}catch(e){msg(e.message)}}async function rollback(){if(confirm('Revert generated nginx config to its previous revision?'))try{await api('rollback',{method:'POST'});clearForm();load()}catch(e){msg(e.message)}}load()</script>'''
