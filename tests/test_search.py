"""Тесты гибридного поиска (Задача 5, критерии из ТЗ).

Проверяются: релевантность выдачи на реальном сид-каталоге, фильтр по
статусам (closed не попадает), лимит, сортировка по скору и то, что пустой
результат возвращается пустым списком, а не ошибкой.
"""

from __future__ import annotations

from app.models import OpportunityStatus
from app.services.search import DEFAULT_LIMIT, search


def test_ai_project_query_returns_relevant_results(db) -> None:
    """«хочу в проект по ИИ» → непустая релевантная выдача с тегом про ИИ."""
    results = search("хочу в проект по ИИ", db)
    assert results, "поиск не должен возвращать пустой список для темактического запроса"
    assert len(results) <= DEFAULT_LIMIT

    # Хотя бы половина выдачи связана с ИИ/ML через теги или название.
    relevant = [
        r for r in results
        if any(t.lower() in ("ии", "ai", "искусственный интеллект", "ml", "машинное обучение")
               for t in r.opportunity.tags)
        or "ии" in r.opportunity.title.lower()
        or "ai" in r.opportunity.title.lower()
        or "искусственн" in r.opportunity.title.lower()
    ]
    assert len(relevant) >= max(1, len(results) // 2)


def test_results_sorted_by_score_desc(db) -> None:
    """Выдача отсортирована по убыванию релевантности."""
    scores = [r.score for r in search("лаборатория анализ данных", db)]
    assert scores == sorted(scores, reverse=True)


def test_closed_opportunities_excluded(db) -> None:
    """Записи со статусом closed никогда не попадают в выдачу."""
    queries = [
        "хакатон",
        "хочу в проект по ИИ",
        "мероприятие нетворкинг",
        "стартап акселератор",
    ]
    for query in queries:
        for result in search(query, db):
            status_value = getattr(result.opportunity.status, "value", result.opportunity.status)
            assert status_value != OpportunityStatus.CLOSED.value, (
                f"closed-запись {result.opportunity.title!r} в выдаче {query!r}"
            )


def test_grant_query_finds_umnik(db) -> None:
    """Запрос про грант «УМНИК» находит именно эту возможность."""
    results = search("нужен грант умник стартап", db)
    titles = [r.opportunity.title for r in results]
    assert any("умник" in t.lower() for t in titles), f"в выдаче нет УМНИКа: {titles}"


def test_empty_and_garbage_queries_return_empty_list(db) -> None:
    """Пустой запрос и запрос без совпадений → пустой список, не ошибка."""
    assert search("", db) == []
    assert search("   ", db) == []
    assert search("квантовая хромодинамика круассанов", db) == []


def test_limit_respected(db) -> None:
    """Лимит выдачи соблюдается даже при большом числе кандидатов."""
    results = search("ии", db, limit=3)
    assert len(results) <= 3
