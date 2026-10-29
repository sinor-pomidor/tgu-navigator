"""Проверка seed-каталога: живость source_url и отсутствие персональных данных.

Запуск: python tools/check_seed_sources.py [--offline]
Без сети (--offline) проверяется только эвристика на ПДн.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "seed" / "opportunities.json"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+7[\d ()\-]{6,}")
# ФИО-подобные последовательности (Имя Фамилия) — эвристика.
NAME_RE = re.compile(
    r"\b[А-Я][а-я]{2,}\s+[А-Я][а-я]{2,}(?:ов|ева|ич|овна|ский|ская)\b"
)
# Разрешённые публичные email подразделений (не персональные).
ALLOWED_EMAIL_DOMAINS = ("@tsu.ru", "@mail.tsu.ru", "@ya.ru", "@gmail.com")


def check_pii(data: list[dict]) -> list[str]:
    """Вернуть список нарушений персональных данных в записях."""
    problems: list[str] = []
    for i, item in enumerate(data):
        title = item.get("title", f"#{i}")
        contact = str(item.get("contact", "") or "")
        # Email в contact допустим только корпоративный общий.
        for m in EMAIL_RE.finditer(contact):
            if not m.group(0).lower().endswith(ALLOWED_EMAIL_DOMAINS):
                problems.append(f"{title}: подозрительный email {m.group(0)}")
        if PHONE_RE.search(json.dumps(item, ensure_ascii=False)):
            problems.append(f"{title}: найден личный телефон")
        text = " ".join(
            str(v) for k, v in item.items() if k in ("description", "requirements", "audience", "contact")
        )
        for m in NAME_RE.finditer(text):
            problems.append(f"{title}: возможно ФИО '{m.group(0)}'")
    return problems


def check_links(data: list[dict]) -> list[str]:
    """Проверить доступность source_url (HTTP < 400). Требует сеть."""
    import requests

    broken: list[str] = []
    for item in data:
        url = item.get("source_url", "")
        title = item.get("title", "?")
        if not url:
            broken.append(f"{title}: пустой source_url")
            continue
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code >= 400:
                resp = requests.get(url, timeout=15, allow_redirects=True,
                                    headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code >= 400:
                broken.append(f"{title}: HTTP {resp.status_code} для {url}")
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{title}: ошибка сети {exc}")
    return broken


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="не проверять ссылки по сети")
    args = parser.parse_args(argv)
    data = json.loads(SEED.read_text(encoding="utf-8"))
    print(f"Записей в сиде: {len(data)}")
    ok = True
    pii = check_pii(data)
    if pii:
        ok = False
        print("НАРУШЕНИЯ ПДн:")
        for p in pii:
            print("  -", p)
    else:
        print("Персональные данные: не найдены ✓")
    if not args.offline:
        broken = check_links(data)
        if broken:
            ok = False
            print("БИТЫЕ ССЫЛКИ:")
            for b in broken:
                print("  -", b)
        else:
            print("Ссылки: все доступны ✓")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
