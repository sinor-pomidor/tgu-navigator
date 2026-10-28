"""CSV-импорт мероприятий для кураторов (задача I5).

Кураторы группы/факультета заполняют простой шаблон ``seed/events_template.csv``
и запускают импорт одной командой::

    python -m app.ingestion.csv_import seed/events_template.csv
    python -m app.ingestion.csv_import seed/events_template.csv --dry-run

Формат файла (кодировка UTF-8, разделитель — запятая):

    title, description, deadline, contact, source_url, tags

* ``title`` и ``source_url`` — обязательны: строки без них отклоняются
  с причиной в итоговом отчёте (запись без официального источника в БД
  не попадает);
* ``tags`` — несколько тегов через точку с запятой («ИИ; NLP»);
* ``deadline`` — ГГГГ-ММ-ДД или ГГ.ММ.ГГГГ, может быть пустым; прошедшая
  дата автоматически переводит запись в статус ``closed``;
* необязательные колонки ``type``, ``requirements``, ``audience``,
  ``external_id`` поддерживаются обратно совместимо: если колонок нет —
  используются значения по умолчанию (``type='event'``).

Правила записи: импортированные строки попадают в каталог как
``origin='manual'`` — конвейер автоматического сбора (парсер сайта ТГУ)
такие записи никогда не перезаписывает и не удаляет. Дедупликация при
повторном импорте идёт по ``source_url`` среди manual-записей этого же
источника-импорта: найденная запись обновляется, а не удваивается.

Логика реализована источником ``CsvCuratorSource`` (реестр источников) и
функцией ``import_csv_file`` (прямой вызов/CLI).
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import init_db, session_scope
from app.ingestion.base import BaseSource, RawItem
from app.ingestion.normalize import IngestReport, derive_status, normalize_title
from app.models import Opportunity, OpportunityOrigin, OpportunityStatus, OpportunityType
from app.progress import progress_bar

logger = logging.getLogger(__name__)

#: Путь к шаблону для кураторов (относительно корня проекта).
TEMPLATE_PATH = "seed/events_template.csv"

#: Минимально обязательный набор колонок шаблона I5.
REQUIRED_COLUMNS = ("title", "source_url")

#: Необязательные, но поддерживаемые колонки (обратная совместимость с
#: расширенным шаблоном seed/curator_import_template.csv).
OPTIONAL_COLUMNS = (
    "description",
    "deadline",
    "contact",
    "tags",
    "type",
    "requirements",
    "audience",
    "external_id",
)

#: Допустимые значения колонки type (совпадают с OpportunityType).
VALID_TYPES = {t.value for t in OpportunityType}


def parse_deadline(value: str | None) -> date | None:
    """Разбирает дату дедлайна из CSV: ISO (2026-11-15) или ру (15.11.2026).

    Returns:
        ``date`` либо None, если значение пустое или не читается как дата
        (негодная дата не роняет импорт — строка импортируется без дедлайна,
        причина фиксируется в логе).
    """
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
    """Источник «CSV-файл от кураторов».

    Читает файл, валидирует структуру колонок и превращает каждую строку
    в ``RawItem``; мусорные строки (пустые title/source_url) отбраковываются
    на этапе чтения с записью причины в ``self.rejected_rows``.
    """

    name = "csv_import"

    def __init__(self, file_path: str | Path) -> None:
        self.path = Path(file_path)
        #: Причины отклонения строк при чтении (строка, причина).
        self.rejected_rows: list[str] = []

    def fetch(self) -> list[RawItem]:
        """Читает CSV и возвращает список «сырых» записей.

        Raises:
            FileNotFoundError: файл не найден.
            ValueError: файл пуст или в шапке нет обязательных колонок.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"CSV-файл не найден: {self.path}")

        items: list[RawItem] = []
        self.rejected_rows = []
        with self.path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError("CSV-файл пуст (нет строки заголовков)")
            missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
            if missing:
                raise ValueError(
                    f"В CSV нет обязательных колонок {missing}. "
                    f"Используйте шаблон {TEMPLATE_PATH} "
                    f"(колонки: title, description, deadline, contact, source_url, tags)"
                )
            for row_no, row in enumerate(reader, start=2):
                item = self._row_to_item(row, row_no)
                if item is not None:
                    items.append(item)
        logger.info(
            "CSV %s прочитан: %d годных строк, %d отклонено",
            self.path.name,
            len(items),
            len(self.rejected_rows),
        )
        return items

    def _row_to_item(self, row: dict[str, str], row_no: int) -> RawItem | None:
        """Конвертирует одну строку CSV; битую строку отклоняет с причиной."""
        values = {key: (row.get(key) or "").strip() for key in row if key}
        title = values.get("title", "")
        source_url = values.get("source_url", "")
        if not title:
            self.rejected_rows.append(
                f"строка {row_no}: пустой title — строка пропущена"
            )
            logger.warning("CSV, строка %d: пустой title — пропуск", row_no)
            return None
        if not source_url:
            self.rejected_rows.append(
                f"строка {row_no} «{title[:60]}»: пустой source_url — "
                "запись без официального источника отклонена"
            )
            logger.warning("CSV, строка %d: пустой source_url — пропуск", row_no)
            return None
        item_type = values.get("type", "").lower() or "event"
        if item_type not in VALID_TYPES:
            logger.warning(
                "CSV, строка %d: неизвестный type=%r → считаем event",
                row_no,
                item_type,
            )
            item_type = "event"
        tags = [t.strip() for t in values.get("tags", "").split(";") if t.strip()]
        return RawItem(
            title=title,
            source_url=source_url,
            external_id=values.get("external_id") or None,
            type=item_type,
            description=values.get("description") or None,
            requirements=values.get("requirements") or None,
            audience=values.get("audience") or None,
            tags=tags,
            deadline=parse_deadline(values.get("deadline")),
            contact=values.get("contact") or None,
            source_name=self.name,
            meta={"csv_row": row_no},
        )


def import_manual_items(
    session: Session, items: list[RawItem], source_name: str
) -> IngestReport:
    """Загружает кураторские (manual) записи из CSV в каталог.

    Правила:
      * каждая запись получает ``origin='manual'``;
      * ``source_url`` обязателен — негодные строки отбраковываются с
        причиной в отчёте, процесс импорта не прерывается;
      * дедупликация внутри импорта — по ``source_url`` среди manual-записей
        того же источника: повторный импорт обновляет карточку вместо дубля;
      * статус вычисляется по дедлайну (прошедший → closed).

    Args:
        session: активная сессия SQLAlchemy (транзакцию ведёт вызывающий).
        items: «сырые» записи, прочитанные ``CsvCuratorSource``.
        source_name: имя источника (пишется в колонку ``source``).

    Returns:
        Отчёт: ``imported_manual`` — добавлено, ``updated`` — обновлено
        при повторном импорте, ``rejected``/``errors`` — отклонённые строки.
    """
    report = IngestReport(source_name=source_name, fetched=len(items))
    bar = progress_bar(len(items), "Импорт CSV")

    existing_by_url = {
        (o.source_url or "").strip().lower(): o
        for o in session.scalars(
            select(Opportunity).where(
                Opportunity.origin == OpportunityOrigin.MANUAL,
                Opportunity.source == source_name,
            )
        ).all()
    }

    for idx, item in enumerate(items, start=1):
        bar.update(idx - 1)
        url = (item.source_url or "").strip()
        title = (item.title or "").strip()
        # Обязательные поля: без них строка уходит в отчёт об ошибках,
        # но импорт продолжается (битые строки не ломают процесс).
        if not title:
            report.rejected += 1
            report.errors.append(f"строка {item.meta.get('csv_row', '?')}: пустой title")
            continue
        if not url:
            report.rejected += 1
            report.errors.append(
                f"строка {item.meta.get('csv_row', '?')} «{title[:60]}»: "
                "пустой source_url — запись без официального источника отклонена"
            )
            continue
        if not url.startswith(("http://", "https://")):
            report.rejected += 1
            report.errors.append(
                f"строка {item.meta.get('csv_row', '?')} «{title[:60]}»: "
                f"source_url не является ссылкой: {url!r}"
            )
            continue
        try:
            item_type = OpportunityType(item.type or "event")
        except ValueError:
            report.rejected += 1
            report.errors.append(
                f"строка {item.meta.get('csv_row', '?')} «{title[:60]}»: "
                f"недопустимый type={item.type!r}"
            )
            continue

        fields = {
            "type": item_type,
            "title": title,
            "description": (item.description or "").strip() or None,
            "requirements": (item.requirements or "").strip() or None,
            "audience": (item.audience or "").strip() or None,
            "tags": item.tags,
            "deadline": item.deadline,
            "contact": (item.contact or "").strip() or None,
            "source_url": url,
        }

        target = existing_by_url.get(url.lower())
        if target is not None:
            # Повторный импорт той же ссылки — обновляем карточку куратора.
            for key, value in fields.items():
                setattr(target, key, value)
            target.status = derive_status(item.deadline, OpportunityStatus.OPEN)
            report.updated += 1
            logger.info("Обновлена запись id=%s: %s", target.id, title)
        else:
            record = Opportunity(
                origin=OpportunityOrigin.MANUAL,
                source=source_name,
                status=derive_status(item.deadline, OpportunityStatus.OPEN),
                **fields,
            )
            session.add(record)
            session.flush()
            existing_by_url[url.lower()] = record
            report.imported_manual += 1
            logger.info("Добавлена запись id=%s: %s", record.id, title)

    bar.update(len(items))
    bar.finish()
    return report


def import_csv_file(session: Session, file_path: str | Path) -> IngestReport:
    """Полный цикл импорта CSV-файла куратора в переданную сессию."""
    source = CsvCuratorSource(file_path)
    items = source.fetch()
    report = import_manual_items(session, items, source.name)
    # Причины, выявленные ещё на чтении (пустые title/source_url), — тоже
    # часть итогового отчёта об ошибках.
    report.rejected += len(source.rejected_rows)
    report.errors.extend(source.rejected_rows)
    return report


def main(argv: list[str] | None = None) -> int:
    """Точка входа ``python -m app.ingestion.csv_import <file.csv>``."""
    parser = argparse.ArgumentParser(
        description=(
            "CSV-импорт мероприятий для кураторов "
            f"(шаблон: {TEMPLATE_PATH})"
        )
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=TEMPLATE_PATH,
        help=f"путь к CSV-файлу (по умолчанию {TEMPLATE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="прочитать и проверить файл, но ничего не записывать в БД",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    init_db()
    try:
        with session_scope() as session:
            report = import_csv_file(session, args.csv_file)
            if args.dry_run:
                session.rollback()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Импорт не выполнен: %s", exc)
        return 2

    logger.info("ИТОГ %s", report.summary())
    for error in report.errors:
        logger.info("  • %s", error)
    if report.errors:
        logger.warning(
            "Отклонённые строки не записаны — исправьте их в файле и "
            "повторите импорт (дубликаты по source_url обновляются, а не удваиваются)."
        )
    return 0 if (report.imported_manual or report.updated or args.dry_run) else 1


if __name__ == "__main__":
    sys.exit(main())
