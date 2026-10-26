"""Тесты конвейера сбора данных (ingestion).

Покрывают: миграцию add_origin_fields, CSV-источник, загрузчик
(дедупликация, неприкосновенность ручных записей, даты/статусы),
hygiene и разбор страниц сайта ТГУ на фиксированном HTML (без сети).
"""

from __future__ import annotations

import textwrap
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.db import get_engine, get_session_local
from app.ingest.base import BaseSource, RawItem, SourceRegistry
from app.ingest.loaders import (
    close_stale_parsed,
    derive_status,
    normalize_title,
    upsert_items,
    validate_item,
)
from app.ingest.sources.csv_curator import CsvCuratorSource, parse_deadline
from app.ingest.sources.tsu_site import TsuSiteSource, guess_type, parse_russian_date
from app.migrations.add_origin_fields import STATEMENTS, migrate
from app.models import Opportunity, OpportunityOrigin, OpportunityStatus


@pytest.fixture()
def session():
    """Сессия БД; после теста удаляет созданные тестом parsed-записи."""
    s = get_session_local()()
    created_ids: list[int] = []
    try:
        yield s, created_ids
    finally:
        if created_ids:
            s.query(Opportunity).filter(Opportunity.id.in_(created_ids)).delete(
                synchronize_session=False
            )
            s.commit()
        s.close()


def _item(**kw) -> RawItem:
    base = dict(
        title="Тестовое мероприятие",
        source_url="https://example.tsu.ru/event/1",
        external_id="ext-1",
        type="event",
        tags=["наука"],
    )
    base.update(kw)
    return RawItem(**base)


# --------------------------- миграция -----------------------------------


class TestMigration:
    def test_idempotent_double_run(self):
        """Повторный запуск миграции не падает и не меняет данные."""
        migrate()
        before = _count_opportunities()
        migrate()  # второй раз — без исключений
        assert _count_opportunities() == before

    def test_seed_records_are_manual(self):
        """Все сид-записи помечены origin='manual'."""
        with get_session_local()() as s:
            manual = s.scalar(
                select(Opportunity).where(
                    Opportunity.origin != OpportunityOrigin.MANUAL
                )
            )
        assert manual is None

    def test_statements_use_if_not_exists(self):
        """Каждый DDL идемпотентен по формулировке."""
        assert all("IF NOT EXISTS" in st.upper() or "WHERE" in st for st in STATEMENTS)


def _count_opportunities() -> int:
    with get_session_local()() as s:
        return s.execute(text("SELECT count(*) FROM opportunities")).scalar_one()


# --------------------------- чистые функции ------------------------------


class TestPureHelpers:
    @pytest.mark.parametrize(
        "text_,expected",
        [
            ("15 ноября 2026", date(2026, 11, 15)),
            ("до 29 сентября", date(date.today().year, 9, 29)),
            ("15.11.2026", date(2026, 11, 15)),
            ("даты тут нет", None),
            (None, None),
        ],
    )
    def test_parse_russian_date(self, text_, expected):
        assert parse_russian_date(text_) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-11-15", date(2026, 11, 15)),
            ("15.11.2026", date(2026, 11, 15)),
            ("", None),
            ("не дата", None),
        ],
    )
    def test_parse_deadline(self, value, expected):
        assert parse_deadline(value) == expected

    def test_normalize_title(self):
        assert normalize_title(' «Проект  ИИ»! ') == "проект ии"

    def test_guess_type(self):
        assert guess_type("Стипендиальная программа «Система»", "") == "grant"
        assert guess_type("Х Всероссийская конференция", "") == "event"
        assert guess_type("Открыт прием заявок на конкурс", "") == "project"

    def test_derive_status_by_deadline(self):
        today = date.today()
        assert derive_status(today - timedelta(days=1)) == OpportunityStatus.CLOSED
        assert derive_status(today + timedelta(days=3)) == OpportunityStatus.CLOSING_SOON
        assert derive_status(today + timedelta(days=100)) == OpportunityStatus.OPEN
        assert derive_status(None) == OpportunityStatus.OPEN

    def test_validate_item_rules(self):
        assert validate_item(_item()) is None
        assert validate_item(_item(title=" ")) is not None
        assert validate_item(_item(source_url="ftp://x")) is not None
        assert validate_item(_item(type="banana")) is not None


# --------------------------- CSV-источник --------------------------------


class TestCsvSource:
    def test_template_loads(self):
        src = CsvCuratorSource("seed/curator_import_template.csv")
        items = src.fetch()
        assert len(items) == 2
        assert all(i.source_url.startswith("http") for i in items)
        assert items[0].tags and isinstance(items[0].deadline, date)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            CsvCuratorSource("/nonexistent/file.csv").fetch()

    def test_bad_header_raises(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="обязательных колонок"):
            CsvCuratorSource(bad).fetch()

    def test_skips_empty_rows(self, tmp_path):
        good = tmp_path / "rows.csv"
        good.write_text(
            "type,title,source_url\n"
            ",https://tsu.ru/x,\n"          # нет title
            "event,,https://tsu.ru/y\n"      # нет source_url
            "event,Есть,https://tsu.ru/z\n",
            encoding="utf-8",
        )
        items = CsvCuratorSource(good).fetch()
        assert [i.title for i in items] == ["Есть"]


# --------------------------- загрузчик -----------------------------------


class TestUpsert:
    def test_create_then_update_no_duplicates(self, session):
        s, created = session
        items = [_item(title="Ингест-событие А", external_id="dup-1")]
        r1 = upsert_items(s, items, "test_source")
        s.flush()
        created.extend(o.id for o in s.scalars(
            select(Opportunity).where(Opportunity.source == "test_source")
        ))
        assert (r1.created, r1.updated) == (1, 0)

        r2 = upsert_items(s, items, "test_source")
        assert (r2.created, r2.updated) == (0, 1)
        n = s.scalar(
            select(Opportunity).where(
                Opportunity.source == "test_source",
                Opportunity.external_id == "dup-1",
            ).limit(1)
        )
        assert n is not None
        dup_count = len(s.scalars(
            select(Opportunity).where(Opportunity.source == "test_source")
        ).all())
        assert dup_count == 1
        s.rollback()

    def test_manual_records_untouchable(self, session):
        s, _ = session
        manual = s.scalars(
            select(Opportunity).where(Opportunity.origin == OpportunityOrigin.MANUAL)
        ).first()
        original_desc = manual.description
        # Источник приносит заголовок ручной записи — пропуск, не перезапись.
        item = _item(title=manual.title, external_id=None, source_url="https://x.tsu.ru/1")
        report = upsert_items(s, [item], "test_source")
        assert report.skipped_manual == 1
        s.refresh(manual)
        assert manual.description == original_desc
        s.rollback()

    def test_rejects_invalid_without_crash(self, session):
        s, _ = session
        items = [
            _item(title="Годная", external_id="ok-1"),
            _item(title="Без ссылки", source_url="", external_id="bad-1"),
        ]
        report = upsert_items(s, items, "test_source")
        assert (report.created, report.rejected) == (1, 1)
        assert any("source_url" in e for e in report.errors)
        s.rollback()

    def test_past_deadline_becomes_closed(self, session):
        s, _ = session
        item = _item(title="Прошедшее событие", external_id="past-1",
                     deadline=date(2020, 1, 1))
        upsert_items(s, [item], "test_source")
        s.flush()
        rec = s.scalar(select(Opportunity).where(Opportunity.external_id == "past-1"))
        assert rec.status == OpportunityStatus.CLOSED
        s.rollback()

    def test_hygiene_closes_stale(self, session):
        s, _ = session
        item = _item(title="Устаревшая карточка", external_id="stale-1")
        upsert_items(s, [item], "test_source")
        s.flush()
        rec = s.scalar(select(Opportunity).where(Opportunity.external_id == "stale-1"))
        rec.last_seen_at = datetime.now(timezone.utc) - timedelta(days=60)
        s.flush()  # «просрочка» должна уйти в БД до SQL-запроса hygiene
        closed = close_stale_parsed(s, "test_source", stale_days=45)
        assert closed >= 1
        assert rec.status == OpportunityStatus.CLOSED
        s.rollback()


# --------------------------- сайт ТГУ (без сети) -------------------------


LIST_HTML = textwrap.dedent("""
<html><body>
<a href="/calendar-of-events/den-otkrytyh-dverey-2026/">День открытых дверей ТГУ 2026</a>
<a href="/news/index.php?tag=наука">Новости по тегу</a>
<a href="/">Главная</a>
<a href="/calendar-of-events/">Календарь событий</a>
<a href="/calendar-of-events/korotko">Коротко</a>
</body></html>""")

DETAIL_HTML = textwrap.dedent("""
<html><head><title>ДОД</title></head><body>
<h1>День открытых дверей ТГУ 2026</h1>
<p>Приглашаем абитуриентов и студентов. Мероприятие состоится в главном корпусе.</p>
<p>Регистрация не требуется, при себе иметь студенческий или паспорт.</p>
</body></html>""")


class TestTsuSiteParsing:
    def test_detail_links_heuristics(self, monkeypatch):
        src = TsuSiteSource(start_urls=["https://news.tsu.ru/calendar-of-events/"])
        class FakeResp:
            text = LIST_HTML
            def raise_for_status(self): pass
        monkeypatch.setattr(src, "_get", lambda url: FakeResp())
        links = src._collect_detail_links("https://news.tsu.ru/calendar-of-events/", set())
        assert links == ["https://news.tsu.ru/calendar-of-events/den-otkrytyh-dverey-2026/"]

    def test_parse_detail_to_raw_item(self, monkeypatch):
        src = TsuSiteSource(start_urls=["https://news.tsu.ru/"])
        class FakeResp:
            text = DETAIL_HTML
            def raise_for_status(self): pass
        monkeypatch.setattr(src, "_get", lambda url: FakeResp())
        item = src._parse_detail(
            "https://news.tsu.ru/calendar-of-events/den-otkrytyh-dverey-2026/"
        )
        assert item is not None
        assert item.title.startswith("День открытых дверей")
        assert item.type in {"event", "project"}
        assert item.external_id  # стабильный хеш
        assert item.source_url.startswith("https://news.tsu.ru/")

    def test_registry_extensibility(self):
        """Новый источник подключается регистрацией без правок конвейера."""
        class DummySource(BaseSource):
            name = "dummy"
            def fetch(self): return []
        reg = SourceRegistry()
        reg.register(DummySource())
        assert [s.name for s in reg.all()] == ["dummy"]
