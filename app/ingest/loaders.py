"""Загрузчик конвейера: нормализация, валидация, upsert и hygiene.

Правила качества (см. ТЗ, раздел «Защита качества»):

* Дедупликация: запись из источника идентифицируется парой
  ``(source, external_id)``; при отсутствии ``external_id`` — по
  нормализованному заголовку внутри источника. Повторный забор
  обновляет существующую parsed-запись, а не создаёт дубль.
* Неприкосновенность ручных записей: записи с ``origin='manual'``
  загрузчиком никогда не изменяются и не удаляются — даже если
  источник «принёс» похожий заголовок.
* Даты: прошедший ``deadline`` автоматически переводит статус в
  ``closed``; отсутствующий ``source_url`` — запись отбраковывается.
* Hygiene: parsed-записи, давно не подтверждённые источником
  (``last_seen_at`` старше порога), закрываются автоматически.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Opportunity, OpportunityOrigin, OpportunityStatus, OpportunityType
from app.ingest.base import RawItem

logger = logging.getLogger(__name__)

#: Максимальная длина заголовка в каталоге (как в схеме API).
TITLE_MAX_LEN = 300


def normalize_title(title: str) -> str:
    """Нормализует заголовок для сравнения/дедупликации.

    Схлопывает пробелы, убирает пунктуацию на концах, приводит к нижнему
    регистру. Используется как ключ дедупликации, когда источник не даёт
    стабильного external_id.
    """
    cleaned = re.sub(r"\s+", " ", title.strip().lower())
    cleaned = re.sub(r"[«»\"']+", "", cleaned)
    return cleaned.rstrip(" .—-:")


def _normalize_tags(tags: list[str]) -> list[str]:
    """Убирает пустые теги и дубликаты (без учёта регистра), сохраняет порядок."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags or []:
        value = str(tag).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


@dataclass
class IngestReport:
    """Итоги одного прогона конвейера для одного источника."""

    source_name: str = ""
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped_manual: int = 0
    rejected: int = 0
    closed_stale: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Однострочное человекочитаемое резюме для логов/отчётов."""
        parts = [
            f"источник={self.source_name}",
            f"получено={self.fetched}",
            f"создано={self.created}",
            f"обновлено={self.updated}",
            f"пропущено(ручные)={self.skipped_manual}",
            f"отбраковано={self.rejected}",
            f"закрыто(устаревшие)={self.closed_stale}",
        ]
        if self.errors:
            parts.append(f"ошибок={len(self.errors)}")
        return ", ".join(parts)


def validate_item(item: RawItem) -> str | None:
    """Проверяет «сырую» запись. Возвращает причину отбраковки или None."""
    if not item.title or not item.title.strip():
        return "пустой title"
    if not item.source_url or not item.source_url.strip():
        return "пустой source_url (запись без официального источника не допускается)"
    if not item.source_url.startswith(("http://", "https://")):
        return f"source_url не является ссылкой: {item.source_url!r}"
    try:
        OpportunityType(item.type)
    except ValueError:
        return f"недопустимый type={item.type!r}"
    return None


def upsert_items(session: Session, items: list[RawItem], source_name: str) -> IngestReport:
    """Загружает список записей источника в таблицу opportunities.

    Для каждой записи:
      1. Валидация — негодные отбраковываются с причиной в отчёте.
      2. Поиск существующей parsed-записи того же источника
         (по external_id, иначе по нормализованному заголовку).
      3. Если найдена ручная (manual) запись с тем же заголовком —
         источник игнорируется (ручные данные приоритетнее и неприкосновенны).
      4. Иначе — создание новой либо обновление найденной parsed-записи;
         ``last_seen_at`` выставляется в текущий момент всегда.

    Args:
        session: активная сессия SQLAlchemy (транзакцию ведёт вызывающий).
        items: «сырые» записи от одного источника.
        source_name: имя источника (пишется в колонку ``source``).

    Returns:
        Отчёт о загрузке.
    """
    report = IngestReport(source_name=source_name, fetched=len(items))
    now = datetime.now(timezone.utc)

    existing = session.scalars(
        select(Opportunity).where(Opportunity.source == source_name)
    ).all()

    by_external = {o.external_id: o for o in existing if o.external_id}
    by_title = {
        normalize_title(o.title): o
        for o in existing
        if o.origin == OpportunityOrigin.PARSED
    }
    manual_titles = {
        normalize_title(o.title): o
        for o in session.scalars(
            select(Opportunity).where(Opportunity.origin == OpportunityOrigin.MANUAL)
        ).all()
    }

    for item in items:
        reason = validate_item(item)
        if reason:
            report.rejected += 1
            report.errors.append(f"отбраковано «{item.title[:60]}»: {reason}")
            continue

        title = re.sub(r"\s+", " ", item.title.strip())[:TITLE_MAX_LEN]
        target: Opportunity | None = None

        if item.external_id and item.external_id in by_external:
            target = by_external[item.external_id]
        elif normalize_title(title) in by_title:
            target = by_title[normalize_title(title)]

        # Защита ручных записей: если такой заголовок уже есть у кураторов —
        # автоматическая запись не создаётся.
        if target is None and normalize_title(title) in manual_titles:
            report.skipped_manual += 1
            logger.debug(
                "Пропуск «%s»: совпадает с ручной записью id=%s",
                title,
                manual_titles[normalize_title(title)].id,
            )
            continue

        fields_to_set = {
            "type": OpportunityType(item.type),
            "title": title,
            "description": (item.description or "").strip() or None,
            "requirements": (item.requirements or "").strip() or None,
            "audience": (item.audience or "").strip() or None,
            "tags": _normalize_tags(item.tags),
            "deadline": item.deadline,
            "contact": (item.contact or "").strip() or None,
            "source_url": item.source_url.strip(),
            "external_id": item.external_id,
            "last_seen_at": now,
        }

        if target is not None:
            for key, value in fields_to_set.items():
                setattr(target, key, value)
            target.status = derive_status(item.deadline, target.status)
            report.updated += 1
        else:
            record = Opportunity(
                origin=OpportunityOrigin.PARSED,
                source=source_name,
                status=derive_status(item.deadline, OpportunityStatus.OPEN),
                **fields_to_set,
            )
            session.add(record)
            by_title[normalize_title(title)] = record
            if item.external_id:
                by_external[item.external_id] = record
            report.created += 1

    return report


def derive_status(
    deadline: date | None, current: OpportunityStatus | None = None
) -> OpportunityStatus:
    """Вычисляет статус по дедлайну.

    Прошедший дедлайн → closed; до дедлайна ≤ 14 дней → closing_soon;
    дальше/без дедлайна → open (или остаётся текущий, если он open-ish).
    """
    if deadline is None:
        return current if current in (
            OpportunityStatus.OPEN,
            OpportunityStatus.CLOSING_SOON,
        ) else OpportunityStatus.OPEN
    today = date.today()
    if deadline < today:
        return OpportunityStatus.CLOSED
    if (deadline - today).days <= 14:
        return OpportunityStatus.CLOSING_SOON
    return OpportunityStatus.OPEN


def close_stale_parsed(
    session: Session, source_name: str, stale_days: int, today: date | None = None
) -> int:
    """Hygiene: закрывает parsed-записи источника, давно не подтверждавшиеся.

    Args:
        session: активная сессия.
        source_name: имя источника.
        stale_days: порог молчания источника в днях.
        today: базовая дата (параметр для детерминированных тестов).

    Returns:
        Количество переведённых в closed записей.
    """
    cutoff = (today or date.today()) - timedelta(days=stale_days)
    cutoff_dt = datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc)
    stale = session.scalars(
        select(Opportunity).where(
            Opportunity.source == source_name,
            Opportunity.origin == OpportunityOrigin.PARSED,
            Opportunity.status != OpportunityStatus.CLOSED,
            Opportunity.last_seen_at.is_not(None),
            Opportunity.last_seen_at < cutoff_dt,
        )
    ).all()
    for record in stale:
        record.status = OpportunityStatus.CLOSED
    return len(stale)
