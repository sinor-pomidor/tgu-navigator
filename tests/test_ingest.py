"""Тесты конвейера сбора данных (ingestion).

Покрывают: миграцию add_origin_fields, CSV-источник, загрузчик
(дедупликация, неприкосновенность ручных записей, даты/статусы),
hygiene и разбор страниц сайта ТГУ на фиксированном HTML (без сети).
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_session_local
from app.ingestion.base import BaseSource, RawItem
from app.ingestion.csv_import import (
    CsvCuratorSource,
    import_csv_file,
    parse_deadline,
)
from app.ingestion.csv_import import main as csv_main
from app.ingestion.normalize import (
    close_stale_parsed,
    derive_status,
    normalize_title,
    upsert_items,
    validate_item,
)
from app.ingestion.registry import SourceRegistry
from app.ingestion.sources.tsu_site import TsuSiteSource, guess_type, parse_russian_date
from app.migrations.add_origin_fields import STATEMENTS, migrate
from app.models import (
    Opportunity,
    OpportunityOrigin,
    OpportunityStatus,
    OpportunityType,
)


@pytest.fixture()
def session() -> Iterator[tuple[Session, list[int]]]:
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
        """Боевой шаблон кураторов seed/events_template.csv читается без ошибок."""
        src = CsvCuratorSource("seed/events_template.csv")
        items = src.fetch()
        assert len(items) == 4
        assert not src.rejected_rows
        assert all(i.source_url.startswith("http") for i in items)
        assert all(i.type == "event" for i in items)
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


# --------------------------- CSV-импорт (задача I5) -----------------------


I5_CSV = textwrap.dedent(
    """
    title,description,deadline,contact,source_url,tags
    Хакатон ИИ ТГУ,"Двухдневный хакатон для студентов всех направлений.",2027-03-01,ai@tsu.ru,https://www.tsu.ru/i5-hackathon,"ИИ; хакатон"
    Митап по NLP,"Вечер разборов статей по обработке языка.",,nlp@tsu.ru,https://www.tsu.ru/i5-nlp,NLP; лингвистика
    Конкурс «УМНИК»,"Грант до 250 тыс. руб. на студенческий проект.",2027-06-15,grants@tsu.ru,https://www.tsu.ru/i5-umnik,гранты; исследования
    Сломанная строка без ссылки,"Эта строка обязана быть отклонена.",,bad@tsu.ru,,битый
    """
).lstrip()


def _csv_import_rows(s: Session) -> list[Opportunity]:
    """Все записи импорта кураторов (source='csv_import') в текущей сессии."""
    return s.scalars(
        select(Opportunity).where(Opportunity.source == "csv_import")
    ).all()


class TestCsvImportI5:
    def test_three_valid_one_broken(self):
        """Акцепт I5: 3 валидные строки добавлены, 1 битая — в отчёте об ошибках."""
        with get_session_local()() as s:
            csv_file = Path(__file__).resolve().parent / "_fixtures_i5.csv"
            csv_file.write_text(I5_CSV, encoding="utf-8")
            try:
                report = import_csv_file(s, csv_file)
                assert report.imported_manual == 3
                assert report.rejected == 1
                assert len(report.errors) == 1
                assert "source_url" in report.errors[0]

                rows = _csv_import_rows(s)
                assert len(rows) == 3
                # Импортированные строки — кураторские (manual): конвейер их не трогает.
                assert all(r.origin == OpportunityOrigin.MANUAL for r in rows)
                assert all(r.type == OpportunityType.EVENT for r in rows)
                by_title = {r.title: r for r in rows}
                assert by_title["Хакатон ИИ ТГУ"].tags == ["ИИ", "хакатон"]
                assert by_title["Хакатон ИИ ТГУ"].deadline == date(2027, 3, 1)
                assert by_title["Митап по NLP"].deadline is None
                assert by_title["Митап по NLP"].status == OpportunityStatus.OPEN
            finally:
                ids = [o.id for o in _csv_import_rows(s)]
                if ids:
                    s.query(Opportunity).filter(
                        Opportunity.id.in_(ids)
                    ).delete(synchronize_session=False)
                s.commit()
                csv_file.unlink(missing_ok=True)

    def test_reimport_updates_instead_of_duplicating(self):
        """Повторный импорт того же файла обновляет карточки, а не плодит дубли."""
        with get_session_local()() as s:
            csv_file = Path(__file__).resolve().parent / "_fixtures_i5_re.csv"
            csv_file.write_text(I5_CSV, encoding="utf-8")
            try:
                first = import_csv_file(s, csv_file)
                s.commit()
                assert first.imported_manual == 3
                second = import_csv_file(s, csv_file)
                assert second.imported_manual == 0
                assert second.updated == 3
                assert len(_csv_import_rows(s)) == 3
            finally:
                ids = [o.id for o in _csv_import_rows(s)]
                if ids:
                    s.query(Opportunity).filter(
                        Opportunity.id.in_(ids)
                    ).delete(synchronize_session=False)
                s.commit()
                csv_file.unlink(missing_ok=True)

    def test_cli_main_returns_zero(self, tmp_path: Path):
        """CLI python -m app.ingestion.csv_import не падает на файле с битой строкой."""
        csv_file = tmp_path / "cli_events.csv"
        csv_file.write_text(I5_CSV, encoding="utf-8")
        assert csv_main([str(csv_file)]) == 0
        with get_session_local()() as s:
            ids = [o.id for o in _csv_import_rows(s)]
            try:
                assert len(ids) == 3
            finally:
                if ids:
                    s.query(Opportunity).filter(
                        Opportunity.id.in_(ids)
                    ).delete(synchronize_session=False)
                    s.commit()

    def test_cli_missing_file_returns_two(self, tmp_path: Path):
        """Отсутствующий файл — понятная ошибка и код возврата 2."""
        assert csv_main([str(tmp_path / "nope.csv")]) == 2


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
