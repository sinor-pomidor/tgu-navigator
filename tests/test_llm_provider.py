"""Тесты OpenAI-совместимого провайдера (без сети).

Сетевой слой подменён monkeypatch-ом ``httpx.post`` — реальных запросов
тесты не делают. Проверяются ключевые гарантии:

* карточки и источники формируются из данных поиска, а не из ответа LLM;
* при сетевой ошибке/битом ответе API — безопасный откат на mock;
* при пустой выдаче поиска обращение к сети не происходит вовсе.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.search import search


@pytest.fixture()
def results(db: Session) -> list:
    """Непустая выдача поиска для тестов провайдера."""
    found = search("хочу в проект по ИИ", db)
    assert found, "сид-каталог должен давать результаты"
    return found


class _FakeResponse:
    """Заглушка ответа httpx с нужным поведением."""

    def __init__(self, content: str, *, raise_error: bool = False) -> None:
        self._content = content
        self._raise_error = raise_error

    def raise_for_status(self) -> None:
        if self._raise_error:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}


def _make_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_base="https://fake.local/v1",
        api_key="test-key-not-secret",
        model="test-model",
    )


def test_llm_texts_used_but_cards_from_db(monkeypatch, results) -> None:
    """Ответ LLM влияет только на тексты; карточки/источники — из выдачи."""
    llm_answer = json.dumps(
        {"intro": "Нашли интересное!", "next_step": "Напишите куратору."},
        ensure_ascii=False,
    )
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(llm_answer))

    answer = _make_provider().compose_answer("хочу в проект по ИИ", results)

    assert answer.found is True
    assert answer.intro == "Нашли интересное!"
    assert answer.next_step == "Напишите куратору."
    # Карточки строго соответствуют результатам поиска, не фантазиям модели.
    assert [c.id for c in answer.cards] == [r.opportunity.id for r in results]
    assert {s["url"] for s in answer.sources} == {c.source_url for c in answer.cards}


def test_code_fenced_response_is_parsed(monkeypatch, results) -> None:
    """Модель может обернуть JSON в ``` fences — парсится корректно."""
    fenced = '```json\n{"intro": "Привет", "next_step": "Действуй"}\n```'
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(fenced))

    answer = _make_provider().compose_answer("запрос", results)
    assert answer.intro == "Привет"
    assert answer.next_step == "Действуй"


def test_network_error_falls_back_to_mock(monkeypatch, results) -> None:
    """Любой сбой API → детерминированный mock-ответ, сервис жив."""

    def _explode(*a, **kw):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", _explode)

    answer = _make_provider().compose_answer("хочу в проект по ИИ", results)

    assert answer.found is True
    assert answer.cards, "fallback обязан сохранить карточки из выдачи"
    assert answer.sources, "fallback обязан сохранить источники"


def test_http_error_status_falls_back(monkeypatch, results) -> None:
    """HTTP 5xx от API → откат на mock без исключения."""
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _FakeResponse("{}", raise_error=True),
    )
    answer = _make_provider().compose_answer("хочу в проект по ИИ", results)
    assert answer.cards and answer.sources


def test_empty_intro_falls_back(monkeypatch, results) -> None:
    """LLM вернула пустое вступление → считаем ответ непригодным, откат."""
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _FakeResponse('{"intro": "", "next_step": ""}'),
    )
    answer = _make_provider().compose_answer("хочу в проект по ИИ", results)
    assert answer.intro.strip(), "вступление fallback-ответа непустое"
    assert answer.cards


def test_no_results_no_network_call(results) -> None:
    """Пустая выдача поиска: сеть не трогается, честный «не найдено»."""
    calls: list[Any] = []

    def _spy(*a, **kw):  # pragma: no cover - не должен вызываться
        calls.append(a)
        raise AssertionError("обращение к сети при пустой выдаче запрещено")

    original = httpx.post
    try:
        httpx.post = _spy  # type: ignore[assignment]
        answer = _make_provider().compose_answer("бессмыслица", [])
    finally:
        httpx.post = original  # type: ignore[assignment]

    assert calls == []
    assert answer.found is False
    assert answer.cards == [] and answer.sources == []


def test_prompt_contains_hard_fact_rule(monkeypatch, results) -> None:
    """В system-промпте зашито правило «только переданные факты»."""
    captured: dict[str, Any] = {}

    def _capture(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse('{"intro": "ок", "next_step": "ок"}')

    monkeypatch.setattr(httpx, "post", _capture)
    _make_provider().compose_answer("запрос", results)

    system = captured["payload"]["messages"][0]["content"]
    assert "ТОЛЬКО" in system and "выдумывать" in system.lower()
    # Факты для модели передаются вместе со ссылками источников.
    user = captured["payload"]["messages"][1]["content"]
    assert "source_url" in user
