"""Тесты сборки ответа (сервис answer + mock-провайдер).

Ключевое продуктовое свойство, которое здесь защищается: ответ
ассистента опирается ТОЛЬКО на данные каталога — каждая карточка и
каждый источник существуют в БД, выдуманных ссылок быть не может.

LLM-провайдер — только mock (set в conftest), сеть не требуется.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Opportunity
from app.services.answer import build_answer
from app.services.llm import get_provider
from app.services.llm.mock import MockProvider


def test_provider_is_mock_without_network() -> None:
    """Фабрика при LLM_PROVIDER=mock возвращает MockProvider."""
    assert isinstance(get_provider(), MockProvider)


def test_build_answer_cards_match_database(db: Session) -> None:
    """Каждая карточка /ask соответствует реальной записи из БД."""
    payload = build_answer("хочу в проект по ИИ", db)

    assert payload["found"] is True
    assert payload["cards"], "подборка не должна быть пустой при found=True"

    for card in payload["cards"]:
        opp = db.get(Opportunity, card["id"])
        assert opp is not None, f"карточка ссылается на несуществующую id={card['id']}"
        assert card["title"] == opp.title
        assert card["source_url"] == opp.source_url
        assert card["status"] in ("open", "closing_soon")  # closed не попадёт
        assert card["deadline"] is None or str(opp.deadline) == card["deadline"]


def test_build_answer_sources_are_real_and_deduplicated(db: Session) -> None:
    """Поле sources присутствует всегда; все ссылки — из БД, без дублей."""
    payload = build_answer("грант умник стартап", db)

    assert "sources" in payload
    urls = [s["url"] for s in payload["sources"]]
    assert len(urls) == len(set(urls)), "источники не должны дублироваться"

    known_urls = {o.source_url for o in db.query(Opportunity).all()}
    for url in urls:
        assert url in known_urls, f"источник {url!r} отсутствует в каталоге"
    # У каждой карточки есть источник (без источников ответ не отдаётся).
    assert set(urls) == {c["source_url"] for c in payload["cards"]}


def test_build_answer_not_found_is_honest(db: Session) -> None:
    """Пустая выдача поиска → честный «не найдено», без выдумок."""
    payload = build_answer("гонки на квантовых единорогах", db)

    assert payload["found"] is False
    assert payload["cards"] == []
    assert payload["sources"] == []
    assert "не" in payload["intro"].lower()
    assert payload["next_step"], "должна быть рекомендация переформулировать"


def test_build_answer_echoes_query(db: Session) -> None:
    """В ответе сохраняется исходный запрос пользователя."""
    payload = build_answer("  хочу в лабораторию  ", db)
    assert payload["query"] == "хочу в лабораторию"


def test_ask_endpoint_matches_service_layer(client: TestClient, db: Session) -> None:
    """REST /ask и сервис build_answer отдают одинаковый детерминированный ответ."""
    query = "хочу в проект по ИИ"
    http_payload = client.post("/ask", json={"query": query}).json()
    service_payload = build_answer(query, db)

    assert http_payload["intro"] == service_payload["intro"]
    assert [c["id"] for c in http_payload["cards"]] == [c["id"] for c in service_payload["cards"]]
    assert http_payload["sources"] == service_payload["sources"]
