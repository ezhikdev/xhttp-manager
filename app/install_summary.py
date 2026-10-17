"""Readable installation result; never expose hashes or reset an existing password."""

import argparse
import base64
import hashlib
import hmac
import json
import os
import stat
import sys
from pathlib import Path


def read_config(path):
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )


def matches_password(password, encoded):
    try:
        algorithm, rounds, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        expected = base64.b64decode(digest, validate=True)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt, validate=True), int(rounds)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def saved_password(backup, encoded):
    """Reuse only root-private plaintext already saved by this installer.

    Check against the active hash: a more recent backup may belong to a failed
    password change. Old installations with only a hash remain hash-only.
    """
    candidates = [backup / "new-password.txt"]
    candidates += sorted(
        (p for p in backup.parent.glob("*/new-password.txt") if p != candidates[0]),
        key=lambda p: p.parent.name,
        reverse=True,
    )[:20]
    for path in candidates:
        try:
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
                or metadata.st_size > 16384
            ):
                continue
            password = path.read_text(encoding="utf-8").removesuffix("\n")
            if matches_password(password, encoded):
                return password, path
        except (OSError, UnicodeError):
            continue
    return None, None


def visible(value):
    """Do not let custom credentials inject terminal escape/control sequences."""
    result = []
    for char in str(value):
        if char.isprintable():
            result.append(char)
        elif char == "\n":
            result.append("\\n")
        elif char == "\r":
            result.append("\\r")
        elif char == "\t":
            result.append("\\t")
        else:
            result.append(ascii(char)[1:-1])
    return "".join(result)


def panel_urls(config, settings):
    path = settings["panel_path"]
    urls = []
    for host in config["PANEL_HOSTS"].split():
        host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        url = f"http://{host}{path}"
        if url not in urls:
            urls.append(url)
    return urls


def show_summary(config_path, settings_path, backup, action, stream=None):
    stream = stream or sys.stdout
    config = read_config(config_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    password, password_file = saved_password(backup, config["PANEL_PASSWORD_HASH"])
    color = stream.isatty() and "NO_COLOR" not in os.environ and os.getenv("TERM") != "dumb"

    def paint(value, code):
        return f"\033[{code}m{value}\033[0m" if color else value

    rows = [("XHTTP MANAGER", "1;36")]
    rows.append(
        (
            "Обновление успешно завершено"
            if action == "upgrade"
            else "Установка успешно завершена",
            "32",
        )
    )
    rows.append(("", ""))
    for index, url in enumerate(panel_urls(config, settings)):
        label = "Панель" if index == 0 else "Также"
        rows.append((f"{label:<10} {visible(url)}", "1;36"))
    rows.append((f"{'Логин':<10} {visible(config['PANEL_USER'])}", "1"))
    rows.append(
        (
            f"{'Пароль':<10} "
            + (visible(password) if password is not None else "сохранён — используйте прежний"),
            "1;33",
        )
    )
    width = max(54, max(len(text) for text, _ in rows))
    print(file=stream)
    print(paint("╭" + "─" * (width + 4) + "╮", "2"), file=stream)
    for text, code in rows:
        print(
            paint("│  ", "2") + paint(text, code) + " " * (width - len(text)) + paint("  │", "2"),
            file=stream,
        )
    print(paint("╰" + "─" * (width + 4) + "╯", "2"), file=stream)
    if password_file:
        if action == "upgrade" and password_file.parent != backup:
            print(
                "  Пароль не менялся. Показан сохранённый пароль, проверенный по хешу.", file=stream
            )
        print("  Файл с паролем (только root): " + visible(password_file), file=stream)
    else:
        print("  В системе хранится только хеш: показать прежний пароль невозможно.", file=stream)
        print("  Пароль не сброшен. Для его смены задайте PANEL_PASS при установке.", file=stream)
    print("  Резервная копия: " + visible(backup), file=stream)
    print("  Firewall: настройка и подтверждение правил — в панели.", file=stream)
    if config.get("PANEL_HTTPS_ONLY") == "1":
        print(
            "  Secure-cookie включены: для входа используйте настроенный HTTPS-домен.", file=stream
        )
    else:
        print("  Для защищённого входа используйте HTTPS или доверенную VPN-сеть.", file=stream)
    print(file=stream)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--action", required=True, choices=("install", "upgrade"))
    args = parser.parse_args()
    show_summary(args.config, args.settings, args.backup, args.action)
