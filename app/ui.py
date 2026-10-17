from pathlib import Path

_TEMPLATES = Path(__file__).parent / "templates"
HTML = (_TEMPLATES / "panel.html").read_text(encoding="utf-8")
LOGIN = (_TEMPLATES / "login.html").read_text(encoding="utf-8")
