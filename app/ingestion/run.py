"""CLI-оркестратор конвейера ingestion.

Запуск:
    python -m app.ingestion.run                       # все источники этапа 1 (сайт ТГУ)
    python -m app.ingestion.run --source site         # только парсер сайта
    python -m app.ingestion.run --source csv --csv-file seed/events_template.csv
    python -m app.ingestion.run --dry-run             # без записи в БД (только отчёт)

Конвейер: для каждого зарегистрированного источника — fetch → upsert →
hygiene (закрытие устаревших parsed-записей). Ручные данные (origin='manual',
включая CSV-импорт кураторов) автоматическим конвейером не затрагиваются.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_scope
from app.ingestion.base import BaseSource
from app.ingestion.csv_import import CsvCuratorSource, import_manual_items
from app.ingestion.normalize import (
    IngestReport,
    close_stale_parsed,
    refresh_statuses,
    upsert_items,
)
from app.ingestion.registry import SourceRegistry
from app.ingestion.sources.tsu_site import TsuSiteSource
from app.progress import progress_bar

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Сводка по всем источникам одного прогона."""

    reports: list[IngestReport] = field(default_factory=list)

    def total(self, attr: str) -> int:
        return sum(getattr(r, attr) for r in self.reports)

    def print_summary(self) -> None:
        """Печатает сводку через logging (без print, согласно правилам кода)."""
        for report in self.reports:
            logger.info("ИТОГ %s", report.summary())
            for error in report.errors[:20]:
                logger.info("  • %s", error)
        logger.info(
            "СУММА: получено=%d, создано=%d, обновлено=%d, "
            "импортировано(куратор)=%d, пропущено(ручные)=%d, "
            "отбраковано=%d, закрыто(устаревшие)=%d",
            self.total("fetched"),
            self.total("created"),
            self.total("updated"),
            self.total("imported_manual"),
            self.total("skipped_manual"),
            self.total("rejected"),
            self.total("closed_stale"),
        )


def build_registry(csv_file: str | None) -> SourceRegistry:
    """Собирает реестр источников этапа 1.

    Этап 2 (VK API, Telegram-каналы): добавить сюда ещё один
    ``registry.register(...)`` — остальной код менять не нужно.
    """
    registry = SourceRegistry()
    registry.register(TsuSiteSource())
    if csv_file:
        registry.register(CsvCuratorSource(csv_file))
    return registry


def run_source(session: Session, source: BaseSource, dry_run: bool) -> IngestReport:
    """Прогоняет один источник через конвейер и возвращает отчёт.

    CSV-куратор загружается как ручные записи (origin='manual'); остальные
    источники — как автоматические (parsed) с hygiene-закрытием устаревших.
    При ``dry_run=True`` изменения откатываются транзакцией — в БД ничего
    не попадает, но отчёт формируется полностью.
    """
    settings = get_settings()
    try:
        items = source.fetch()
    except Exception as exc:  # noqa: BLE001 - источник недоступен не должно ронять прогон
        logger.error("Источник %s недоступен: %s", source.name, exc)
        return IngestReport(source_name=source.name, errors=[f"ошибка забора: {exc}"])

    if isinstance(source, CsvCuratorSource):
        report = import_manual_items(session, items, source.name)
        report.rejected += len(source.rejected_rows)
        report.errors.extend(source.rejected_rows)
    else:
        report = upsert_items(session, items, source.name)
        report.closed_stale = close_stale_parsed(
            session, source.name, settings.ingest_stale_days
        )
    if dry_run:
        session.rollback()
        report.errors.append("dry-run: изменения откачены, БД не тронута")
    return report


def main(argv: list[str] | None = None) -> int:
    """Точка входа ``python -m app.ingestion.run``."""
    parser = argparse.ArgumentParser(description="Конвейер сбора данных каталога ТГУ")
    parser.add_argument(
        "--source",
        choices=["all", "site", "csv"],
        default="all",
        help="какой источник запустить (по умолчанию all — сайт ТГУ)",
    )
    parser.add_argument("--csv-file", help="путь к CSV куратора (для --source csv)")
    parser.add_argument(
        "--dry-run", action="store_true", help="прогнать конвейер без записи в БД"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    csv_file: str | None = None
    if args.source in ("all", "csv"):
        if not args.csv_file and args.source == "csv":
            parser.error("--source csv требует --csv-file <путь>")
        csv_file = args.csv_file or "seed/events_template.csv"

    registry = build_registry(csv_file)
    sources = registry.all()
    if args.source == "site":
        sources = [s for s in sources if s.name == "tsu_site"]
    elif args.source == "csv":
        sources = [s for s in sources if s.name == "csv_import"]

    init_db()
    result = RunResult()
    bar = progress_bar(len(sources), "Сбор источников")
    with session_scope() as session:
        for i, source in enumerate(sources, start=1):
            logger.info("Запуск источника: %s", source.describe())
            result.reports.append(run_source(session, source, args.dry_run))
            bar.update(i)
        # Автообновление статусов по дедлайну для всего каталога (включая
        # ручные и seed-записи): прошедший дедлайн -> closed, близкий -> closing_soon.
        changed = refresh_statuses(session)
        logger.info("Автообновление статусов: изменено записей: %d", changed)
        if args.dry_run:
            session.rollback()
    bar.finish()

    result.print_summary()
    ok = any(
        r.fetched or r.created or r.updated or r.imported_manual
        for r in result.reports
    )
    return 0 if ok or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
