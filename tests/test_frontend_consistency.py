"""Согласованность фронтенда: логика app.js опирается на разметку index.html.

Защищает от регрессии «сломанного оформления» (коммит 7b4ff91), когда index.html
был заменён упрощённой версией без id, которые ожидает app.js, из-за чего
диалоговое окно переставало инициализироваться.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_frontend_files_exist() -> None:
    for name in ("index.html", "app.js", "style.css"):
        assert (FRONTEND / name).is_file(), f"отсутствует frontend/{name}"


def test_all_js_element_ids_present_in_html() -> None:
    """Каждый getElementById из app.js должен существовать в index.html."""
    html = _read("index.html")
    js = _read("app.js")
    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_ids = set(re.findall(r'getElementById\("([^"]+)"\)', js))
    missing = js_ids - html_ids
    assert not missing, f"id в app.js отсутствуют в index.html: {sorted(missing)}"


def test_chat_core_elements_present() -> None:
    """Ключевые элементы диалогового окна должны быть в разметке."""
    html = _read("index.html")
    for element_id in (
        "chatArea",
        "userInput",
        "sendBtn",
        "modalOverlay",
        "modalContent",
        "toast",
        "fs1",
        "fl1",
    ):
        assert f'id="{element_id}"' in html, f"в index.html нет элемента #{element_id}"


def test_no_personal_data_in_frontend() -> None:
    """В интерфейсе не должно быть персональных данных demo-пользователя."""
    text = " ".join(_read(n) for n in ("index.html", "app.js", "style.css")).lower()
    for forbidden in ("арин", "тринёв", "тринева", "инноват"):
        assert forbidden not in text, f"в фронтенде найдено упоминание «{forbidden}»"


def test_css_defines_classes_used_by_js_renderer() -> None:
    """Классы, которые генерирует рендер ответов, должны быть описаны в CSS."""
    css = _read("style.css")
    defined = set(re.findall(r"\.([A-Za-z][\w-]*)", css))
    used = {"msg", "bubble", "intro", "cards", "card", "card-head", "card-title",
            "card-summary", "card-meta", "deadline", "card-actions", "btn",
            "next-step", "typing", "modal-field", "modal-footer"}
    missing = used - defined
    assert not missing, f"классы не описаны в style.css: {sorted(missing)}"
