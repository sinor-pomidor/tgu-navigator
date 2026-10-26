"""Источник «CSV-файл от кураторов».

Формат (шаблон: ``seed/curator_import_template.csv``):

    type,title,description,requirements,audience,tags,deadline,contact,source_url,external_id

Правила:
* ``tags`` — несколько тегов через точку с запятой внутри ячейки;
* ``deadline`` — ГГГГ-ММ-ДД (или ГГ.ММ.ГГГГ), может быть пустым;
* ``external_id`` — необязательный стабильный id строки у куратора; если
  пустой — дедупликация идёт по заголовку;
* строки без ``title`` или ``source_url`` отбраковывает загрузчик;
* кодировка UTF-8, разделитель — запятая.

Запуск: python -m app.ingest.run --source csv --csv-file path/to/file.csv
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from app.ingest.base import BaseSource, RawItem

logger = logging.getLogger(__name__)

#: Обязательные колонки шаблона.
REQUIRED_COLUMNS = ("type", "title", "source_url")

#: Допустимые значения колонки type (совпадают с OpportunityType).
VALID_TYPES = {"project", "lab", "event", "grant"}


def parse_deadline(value: str | None) -> date | None:
    """Разбирает дату дедлайна из CSV: ISO (2026-11-15) или ру (15.11.2026)."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    parts = value.replace(".", "-").split("-")
    if len(parts) == 3:
        try:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except ValueError:
            return None
    logger.warning("Не удалось распознать deadline %r — поле оставлено пустым", value)
    return None


class CsvCuratorSource(BaseSource):
    """Читает выгрузку/шаблон CSV, заполненный куратором."""

    name = "csv_import"

    def __init__(self, file_path: str | Path) -> None:
        self.path = Path(file_path)

    def fetch(self) -> list[RawItem]:
        """Читает CSV и превращает строки в RawItem.

        Raises:
            FileNotFoundError: файл не найден.
            ValueError: в шапке нет обязательных колонок.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"CSV-файл не найден: {self.path}")

        items: list[RawItem] = []
        with self.path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError("CSV-файл пуст (нет строки заголовков)")
            missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
            if missing:
                raise ValueError(
                    f"В CSV нет обязательных колонок: {missing}. "
                    "Используйте шаблон seed/curator_import_template.csv"
                )
            for row_no, row in enumerate(reader, start=2):
                item = self._row_to_item(row, row_no)
                if item is not None:
                    items.append(item)
        logger.info("CSV %s прочитан: %d строк-кандидатов", self.path.name, len(items))
        return items

    @staticmethod
    def _row_to_item(row: dict[str, str], row_no: int) -> RawItem | None:
        """Конвертирует одну строку CSV; мусорные строки возвращают None."""
        title = (row.get("title") or "").strip()
        source_url = (row.get("source_url") or "").strip()
        if not title or not source_url:
            logger.warning("CSV, строка %d: пустые title/source_url — пропуск", row_no)
            return None
        item_type = (row.get("type") or "event").strip().lower()
        if item_type not in VALID_TYPES:
            logger.warning(
                "CSV, строка %d: неизвестный type=%r → считаем event", row_no, item_type
            )
            item_type = "event"
        tags = [t.strip() for t in (row.get("tags") or "").split(";") if t.strip()]
        return RawItem(
            title=title,
            source_url=source_url,
            external_id=(row.get("external_id") or "").strip() or None,
            type=item_type,
            description=(row.get("description") or "").strip() or None,
            requirements=(row.get("requirements") or "").strip() or None,
            audience=(row.get("audience") or "").strip() or None,
            tags=tags,
            deadline=parse_deadline(row.get("deadline")),
            contact=(row.get("contact") or "").strip() or None,
            source_name=CsvCuratorSource.name,
            meta={"csv_row": row_no},
        )
