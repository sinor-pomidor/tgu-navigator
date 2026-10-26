"""Тесты HTTP-API: health, CRUD каталога и сценарий /ask (mock-провайдер).

Используются реальные приложение и БД (посадочные данные — сид-каталог),
LLM-провайдер принудительно mock, поэтому тесты не требуют интернета.
Созданные в тестах записи удаляются (фикстура cleanup_opportunity_ids из conftest).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

VALID_OPPORTUNITY = {
    "type": "project",
    "title": "Тестовый проект по компьютерному зрению",
    "description": "Сегментация снимков для студенческого исследования.",
    "requirements": "Знание Python, готовность 8 часов в неделю.",
    "audience": "студенты 2–4 курса, ВМК",
    "tags": ["ИИ", "computer vision", "Python"],
    "deadline": "2026-12-30",
    "status": "open",
    "contact": "cv-lab@ttu.ru",
    "source_url": "https://example.edu/tvu/test-cv-project",
}


# Удаление созданных записей после теста обеспечивает фикстура
# cleanup_opportunity_ids из conftest.py (независимость тестов).


# ------------------------------ health ---------------------------------


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ------------------------------ CRUD -----------------------------------


def test_list_opportunities_returns_seed_catalog(client: TestClient) -> None:
    response = client.get("/opportunities")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 15  # сид-каталог загружен
    first = data[0]
    for field in ("id", "type", "title", "tags", "status", "source_url"):
        assert field in first


def test_list_filters_by_type_and_status(client: TestClient) -> None:
    grants = client.get("/opportunities", params={"type": "grant"}).json()
    assert grants and all(g["type"] == "grant" for g in grants)

    closing = client.get(
        "/opportunities", params={"status": "closing_soon"}
    ).json()
    assert closing and all(o["status"] == "closing_soon" for o in closing)


def test_list_search_by_substring(client: TestClient) -> None:
    found = client.get("/opportunities", params={"q": "УМНИК"}).json()
    assert any("умник" in o["title"].lower() for o in found)

    empty = client.get("/opportunities", params={"q": "нет такой строки 12345"}).json()
    assert empty == []


def test_get_create_update_delete_cycle(client: TestClient, cleanup_opportunity_ids) -> None:
    # Создание → 201 и поля echoes.
    created = client.post("/opportunities", json=VALID_OPPORTUNITY)
    assert created.status_code == 201
    body = created.json()
    oid = body["id"]
    cleanup_opportunity_ids.append(oid)
    assert body["title"] == VALID_OPPORTUNITY["title"]
    assert body["status"] == "open"
    assert body["created_at"] and body["updated_at"]

    # Чтение по id.
    fetched = client.get(f"/opportunities/{oid}")
    assert fetched.status_code == 200
    assert fetched.json()["tags"] == ["ИИ", "computer vision", "Python"]

    # Обновление (частичное): статус и дубликаты тегов нормализуются.
    updated = client.put(
        f"/opportunities/{oid}",
        json={"status": "closing_soon", "tags": ["ИИ", "ии", "ML"]},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "closing_soon"
    assert updated.json()["tags"] == ["ИИ", "ML"]  # дубль без учёта регистра убран

    # Удаление → повторный GET даёт 404.
    assert client.delete(f"/opportunities/{oid}").status_code == 204
    assert client.get(f"/opportunities/{oid}").status_code == 404


def test_get_missing_returns_404(client: TestClient) -> None:
    assert client.get("/opportunities/999999").status_code == 404


def test_validation_errors_return_422(client: TestClient) -> None:
    bad_type = dict(VALID_OPPORTUNITY, type="unknown_type")
    assert client.post("/opportunities", json=bad_type).status_code == 422

    no_title = {k: v for k, v in VALID_OPPORTUNITY.items() if k != "title"}
    assert client.post("/opportunities", json=no_title).status_code == 422

    empty_title = dict(VALID_OPPORTUNITY, title="   ")
    assert client.post("/opportunities", json=empty_title).status_code == 422

    no_source = {k: v for k, v in VALID_OPPORTUNITY.items() if k != "source_url"}
    assert client.post("/opportunities", json=no_source).status_code == 422


# ------------------------------- /ask ----------------------------------


def test_ask_with_results_has_cards_and_sources(client: TestClient) -> None:
    response = client.post("/ask", json={"query": "хочу в проект по ИИ"})
    assert response.status_code == 200
    data = response.json()

    assert data["found"] is True
    assert data["intro"]
    assert 1 <= len(data["cards"]) <= 5
    assert "sources" in data and data["sources"]

    card = data["cards"][0]
    for field in ("title", "type", "summary", "source_url", "status"):
        assert card[field], f"карточке не хватает поля {field}"
    # Каждый источник — официальная ссылка из карточки.
    source_urls = {s["url"] for s in data["sources"]}
    assert source_urls.issubset({c["source_url"] for c in data["cards"]})


def test_ask_no_results_is_honest_not_found(client: TestClient) -> None:
    response = client.post("/ask", json={"query": "гонки на квантовых единорогах"})
    assert response.status_code == 200
    data = response.json()

    assert data["found"] is False
    assert data["cards"] == []
    assert data["sources"] == []
    assert "не" in data["intro"].lower()  # честный ответ «не найдено»
    assert data["next_step"]  # рекомендация переформулировать


def test_ask_empty_query_rejected(client: TestClient) -> None:
    assert client.post("/ask", json={"query": ""}).status_code == 422
    assert client.post("/ask", json={}).status_code == 422
