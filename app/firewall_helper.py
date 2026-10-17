#!/opt/xhttp-manager/venv/bin/python
"""Root-owned entry point. Only fixed operations and validated JSON are accepted."""

import fcntl
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

# Never import from CWD, PYTHONPATH, or a service-user-writable directory.
sys.path.insert(0, "/opt/xhttp-manager")
from app.firewall import TABLE, Policy, permitted, render_policy

STATE = Path("/var/lib/xhttp-manager-firewall")
HELPER = "/usr/local/sbin/xhttp-manager-firewall"


def run(args, text=None, check=True):
    result = subprocess.run(
        args,
        input=text,
        text=True,
        capture_output=True,
        timeout=20,
        env={**os.environ, "LC_ALL": "C"},
    )
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1400:])
    return result


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def save(path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def current_table():
    result = run(["/usr/sbin/nft", "-s", "list", "table", "inet", TABLE], check=False)
    if result.returncode:
        # Missing table is expected. Permission, binary and kernel errors are not.
        if "No such file" not in result.stderr and "does not exist" not in result.stderr:
            raise RuntimeError(result.stderr[-1400:])
        return None
    return result.stdout


def replace_table(text):
    prefix = f"delete table inet {TABLE}\n" if current_table() else ""
    batch = prefix + (text or "")
    if batch:
        run(["/usr/sbin/nft", "-c", "-f", "-"], batch)
        run(["/usr/sbin/nft", "-f", "-"], batch)


def endpoint(value):
    host, port = value.rsplit(":", 1)
    return host.strip("[]").split("%")[0], int(port)


def protect_access(policy, peer):
    ipaddress.ip_address(peer)
    if not permitted(policy, 80, peer):
        raise ValueError("Правило блокирует текущий IP панели на TCP 80.")
    listeners = run(["/usr/bin/ss", "-H", "-ltnp"]).stdout
    ports = {22}
    for line in listeners.splitlines():
        if '"sshd"' in line or '"systemd"' in line and "ssh" in line:
            ports.add(endpoint(line.split()[3])[1])
    # ssh.socket can own a custom listening port while sshd is not running.
    if Path("/usr/sbin/sshd").is_file():
        configured = run(["/usr/sbin/sshd", "-T"], check=False)
        if configured.returncode:
            raise ValueError("Cannot validate sshd configuration; refusing firewall changes.")
        for match in re.findall(r"^port ([0-9]+)$", configured.stdout, re.MULTILINE):
            ports.add(int(match))
    for unit in ("ssh.socket", "sshd.socket"):
        sockets = run(
            ["/usr/bin/systemctl", "show", unit, "--property=Listen", "--value"], check=False
        )
        if not sockets.returncode:
            ports.update(int(p) for p in re.findall(r":([0-9]+)\s+\(Stream\)", sockets.stdout))
    # Preserve access for all currently connected SSH peers, not only the web peer.
    sessions = run(["/usr/bin/ss", "-H", "-tnp", "state", "established"]).stdout
    peers = {}
    for line in sessions.splitlines():
        columns = line.split()
        if len(columns) >= 4:
            try:
                local, port = endpoint(columns[2])
                remote, _ = endpoint(columns[3])
                if port in ports:
                    peers.setdefault(port, set()).add(remote)
            except (ValueError, IndexError):
                continue
    for port in ports:
        rule = next((r for r in policy.rules if r.protocol == "tcp" and r.port == port), None)
        if rule and (rule.action == "deny" or rule.sources and not peers.get(port)):
            raise ValueError(
                f"Нельзя закрыть SSH-порт {port} или ограничить его без активной SSH-сессии."
            )
        addresses = peers.get(port, {peer})
        if not all(permitted(policy, port, address) for address in addresses):
            raise ValueError(f"Правила блокируют активный SSH-доступ на порту {port}.")
    if policy.trusted_interfaces:
        links = json.loads(run(["/usr/sbin/ip", "-d", "-j", "link", "show"]).stdout)
        safe = {
            x["ifname"]
            for x in links
            if x.get("linkinfo", {}).get("info_kind")
            in ("bridge", "veth", "tun", "wireguard", "dummy")
        }
        if not set(policy.trusted_interfaces) <= safe:
            raise ValueError(
                "Доверенными могут быть только существующие внутренние виртуальные интерфейсы."
            )


def expired(pending):
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return (
        pending.get("boot_id") != boot or pending.get("monotonic_deadline", 0) <= time.monotonic()
    )


def remaining(pending):
    return max(0, int(pending["monotonic_deadline"] - time.monotonic() + 0.999))


def rollback_pending(pending):
    replace_table(pending["previous"])
    (STATE / "pending.json").unlink(missing_ok=True)


def operate(action, payload):
    committed = read(STATE / "committed.json", {"enabled": False, "policy": Policy().model_dump()})
    pending = read(STATE / "pending.json")
    if pending and expired(pending):
        rollback_pending(pending)
        pending = None
    if action == "status":
        return {
            **committed,
            "policy": pending["policy"] if pending else committed["policy"],
            "active": current_table() is not None,
            "pending": {
                "deadline": pending["deadline"],
                "peer": pending["peer"],
                "token": pending["token"],
                "remaining": remaining(pending),
            }
            if pending
            else None,
            "defaults": [22, 80, 443, 2222],
        }
    if action == "apply":
        if pending:
            raise ValueError("Сначала подтвердите или отмените предыдущее изменение.")
        policy = Policy.model_validate(payload["policy"])
        peer = str(ipaddress.ip_address(payload["peer"]))
        protect_access(policy, peer)
        token = secrets.token_urlsafe(32)
        unit = "xhttp-manager-fw-" + secrets.token_hex(8)
        pending = {
            "policy": policy.model_dump(),
            "previous": current_table(),
            "peer": peer,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "token": token,
            "deadline": time.time() + 120,
            "unit": unit,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "monotonic_deadline": time.monotonic() + 120,
        }
        save(STATE / "pending.json", pending)
        try:
            # Independent root-owned timer survives application crashes and logout.
            run(
                [
                    "/usr/bin/systemd-run",
                    "--quiet",
                    "--unit=" + unit,
                    "--on-active=120s",
                    "--timer-property=AccuracySec=1s",
                    HELPER,
                    "expire",
                ]
            )
            replace_table(render_policy(policy))
        except Exception:
            # nft is atomic: failure leaves the previous table in place.
            (STATE / "pending.json").unlink(missing_ok=True)
            raise
        return {
            "token": token,
            "deadline": pending["deadline"],
            "remaining": remaining(pending),
            "policy": policy.model_dump(),
        }
    if action == "confirm":
        if not pending:
            raise ValueError("Нет ожидающих подтверждения правил.")
        if not hmac.compare_digest(
            pending["token_hash"], hashlib.sha256(payload.get("token", "").encode()).hexdigest()
        ):
            raise ValueError("Неверный токен подтверждения.")
        if payload.get("peer") != pending["peer"]:
            raise ValueError("Подтверждение должно прийти с IP, применившего правила.")
        # Commit only after the policy has survived a second authenticated request.
        save(STATE / "committed.json", {"enabled": True, "policy": pending["policy"]})
        (STATE / "pending.json").unlink(missing_ok=True)
        return {"ok": True}
    if action in ("cancel", "expire"):
        if pending and (action == "cancel" or expired(pending)):
            rollback_pending(pending)
        return {"ok": True}
    if action == "disable":
        if pending:
            rollback_pending(pending)
        replace_table(None)
        save(STATE / "committed.json", {**committed, "enabled": False})
        return {"ok": True}
    if action == "restore":
        # After reboot discard an unconfirmed candidate and restore committed state.
        if pending:
            rollback_pending(pending)
        if committed["enabled"]:
            replace_table(render_policy(Policy.model_validate(committed["policy"])))
        return {"ok": True}
    raise ValueError("Unsupported operation")


def main():
    if os.geteuid() != 0:
        raise PermissionError("This helper must run as root")
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.is_symlink() or STATE.stat().st_uid != 0:
        raise PermissionError("Invalid firewall state directory")
    with (STATE / "lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        action = sys.argv[1] if len(sys.argv) == 2 else ""
        if action not in ("status", "apply", "confirm", "cancel", "expire", "restore", "disable"):
            raise ValueError("Unsupported operation")
        text = sys.stdin.read(131073) if action in ("apply", "confirm") else "{}"
        if len(text) > 131072:
            raise ValueError("Request too large")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
        print(json.dumps(operate(action, payload)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
