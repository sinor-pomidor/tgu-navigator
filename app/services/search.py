"""Гибридный поиск по каталогу возможностей (Задача 5).

Стратегия на этапе прототипа (без тяжёлых эмбеддинговых моделей):

1. Запрос нормализуется: приводится к нижнему регистру, разбивается на
   слова; служебные «слова-паразиты» («я», «хочу», «нужен», «попасть»,
   предлоги и местоимения) отбрасываются — остаются содержательные токены,
   включая слова-темы («проект», «лаборатория», «грант»). Слова,
   встречающиеся в запросе более одного раза, удваиваются (повтор = явный
   акцент темы).
2. Релевантность считается как сумма взвешенных сигналов:
   * trigram-подобие всего запроса к title/description (pg_trgm) — фон;
   * совпадение значимых слов запроса с ТЕГАМИ записи — сильный сигнал
     (+0.6 за точное совпадение, +0.3 за trigram-близкое >= 0.4);
   * вхождение значимого слова в название/описание — умеренный сигнал
     (+0.35 в title, +0.15 в description за каждое слово).
3. Учитывается только «живой» контент: статусы open/closing_soon.
   Порог отсечки отсекает шумовые trigram-совпадения.
4. Результат сортируется по убыванию скора, лимит — 5 записей.

Если расширение pg_trgm недоступно, модуль деградирует до простого
ILIKE-поиска по названию/описанию/тегам — публичный API ``search``
не меняется, архитектура остаётся расширяемой.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Opportunity

logger = logging.getLogger(__name__)

#: Максимальное число выдачи (по ТЗ).
DEFAULT_LIMIT = 5

#: Порог отсечки нерелевантных результатов. Рассчитан так, чтобы одиночное
#: слабое trigram-совпадение с полным запросом не попадало в выдачу.
MIN_SCORE = 0.30

#: Слова, которые ничего не говорят о теме запроса (шаблонные обороты
#: студенческой фразы: «Я учусь… хочу… интересуюсь… мне нужен…»).
_STOPWORDS: frozenset[str] = frozenset(
    {
        "я", "мы", "ты", "он", "она", "оно", "они",
        "и", "в", "во", "на", "с", "со", "к", "ко", "по", "из", "от",
        "до", "для", "над", "под", "об", "о", "у", "за", "про",
        "не", "ни", "ну", "да", "нет", "же", "бы", "ли", "или", "а",
        "что", "как", "где", "когда", "чем", "чего", "кому",
        "хочу", "хочется", "хотел", "желаю", "мечтаю", "планирую",
        "собираюсь", "надо", "нужен", "нужна", "нужно", "нужные",
        "интересуюсь", "интересно", "увлекаюсь", "занимаюсь",
        "попасть", "принять", "участвовать", "поучаствовать",
        "искать", "ищу", "ищем", "найти", "подобрать", "посоветуй",
        "посоветуйте", "расскажи", "расскажите", "помоги", "помогите",
        "учусь", "учеба", "учёба", "курс", "курсы", "курсе", "факультет",
        "факультета", "институт", "института",
        "универ", "университет", "университета", "тгу",
        "томск", "томске", "томского",
        "реальный", "реальные", "реальному", "настоящий", "настоящие",
        "классный", "крутой", "интересный", "интересные",
        "мне", "меня", "мной", "нас", "нами", "тебе", "вам", "вас",
        "этот", "эта", "это", "эти", "такой", "такая", "такие",
        "какой", "какая", "какие", "любой", "любая", "любые",
        "еще", "ещё", "уже", "совсем", "очень", "немного", "прямо",
        "год", "года", "году", "лет", "сейчас", "потом", "можно",
        "нельзя", "есть", "быть", "буду", "стал", "стала",
    }
)

_WORD_RE = re.compile(r"[а-яa-z0-9][а-яa-z0-9\-']*", flags=re.IGNORECASE)


@dataclass(frozen=True)
class SearchResult:
    """Одна выдача поиска: запись каталога и её релевантность."""

    opportunity: Opportunity
    score: float


def tokenize(query: str) -> list[str]:
    """Возвращает значимые слова запроса для бонусов по тегам и тексту.

    Токены короче 2 символов и служебные стоп-слова отбрасываются. Если
    после фильтрации ничего не осталось, возвращаем все слова длиной >= 2
    — иначе искать нечем. Уникальные слова идут в алфавитном порядке
    (детерминированно); слово, повторённое в запросе, добавляется ещё раз
    в конец — это заметный, но ограниченный вклад в скор.
    """
    words = [w.lower() for w in _WORD_RE.findall(query or "")]
    meaningful = [w for w in words if len(w) >= 2 and w not in _STOPWORDS]
    if not meaningful:
        return sorted(w for w in words if len(w) >= 2)
    unique = sorted(set(meaningful))
    repeated = sorted({w for w in meaningful if meaningful.count(w) > 1})
    return unique + repeated


def _pg_trgm_available(eng: Engine) -> bool:
    """Проверяет, установлено ли расширение pg_trgm в БД."""
    try:
        with eng.connect() as conn:
            found = conn.execute(
                sql_text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            ).scalar()
        return found is not None
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось проверить доступность pg_trgm", exc_info=True)
        return False


# Основной SQL гибридного поиска. Все сигналы считаются в SQL над
# набором значимых слов :words (text[]) и полным запросом :query:
#   sim_title/sim_desc — фоновое trigram-подобие целому запросу;
#   tag_score          — совпадения слов с тегами (unnest);
#   text_score         — вхождение слов в title (0.35) и description (0.15).
# Закрытые возможности исключаются полностью.
_SQL_SEARCH = sql_text(
    """
    SELECT o.id,
           sim_title.sim                                    AS sim_title,
           sim_desc.sim                                     AS sim_desc,
           COALESCE(tag_bonus.score, 0.0)                   AS tag_score,
           COALESCE(text_bonus.score, 0.0)                  AS text_score,
           sim_title.sim + 0.6 * sim_desc.sim
             + COALESCE(tag_bonus.score, 0.0)
             + COALESCE(text_bonus.score, 0.0)              AS score
      FROM opportunities AS o
      CROSS JOIN LATERAL (
        SELECT COALESCE(similarity(o.title, :query), 0.0) AS sim
      ) AS sim_title
      CROSS JOIN LATERAL (
        SELECT COALESCE(similarity(o.description, :query), 0.0) AS sim
      ) AS sim_desc
      LEFT JOIN LATERAL (
        SELECT sum(CASE WHEN lower(t.tag) = w.word THEN 0.6
                        WHEN similarity(lower(t.tag), w.word) >= 0.4
                        THEN 0.3 ELSE 0.0 END) AS score
          FROM unnest(o.tags) AS t(tag)
          JOIN unnest(CAST(:words AS text[])) AS w(word)
            ON lower(t.tag) = w.word
            OR similarity(lower(t.tag), w.word) >= 0.4
      ) AS tag_bonus ON TRUE
      LEFT JOIN LATERAL (
        SELECT sum(CASE WHEN position(w.word IN lower(o.title)) > 0 THEN 0.35
                        WHEN position(w.word IN lower(COALESCE(o.description, ''))) > 0
                        THEN 0.15 ELSE 0.0 END) AS score
          FROM unnest(CAST(:words AS text[])) AS w(word)
      ) AS text_bonus ON TRUE
     WHERE o.status IN ('open', 'closing_soon')
     ORDER BY score DESC, o.id ASC
     LIMIT :limit
    """
)

# Деградированный поиск (без pg_trgm): SQL-кандидаты по подстроке +
# Python-ранжирование. Ищем каждое значимое слово запроса в title,
# description и тегах; совпадения с тегами — сильный сигнал (как в
# основном pg_trgm-пути), затем название, затем описание. Быстрое
# нечёткое сравнение (rapidfuzz) ловит опечатки и словоформы
# («проект» ~ «проекты», «иии» ~ «ии»). Один и тот же код работает на
# PostgreSQL (теги — массив, приводим к тексту) и SQLite (теги — JSON).
def _fallback_search(
    needle: str, session: Session, limit: int
) -> list[SearchResult]:
    """Поиск без pg_trgm: подстрока + нечёткое ранжирование в Python.

    Args:
        needle: нормализованный запрос (нижний регистр).
        session: активная сессия БД.
        limit: максимальное число результатов.

    Returns:
        Отсортированный список ``SearchResult``; пустой список, если
        ничего не найдено.
    """
    from rapidfuzz import fuzz  # локальный импорт: зависимость лёгкая

    words = tokenize(needle) or [needle]
    is_sqlite = (
        session.bind is not None and session.bind.dialect.name == "sqlite"
    )
    tags_expr = (
        "COALESCE(o.tags, '')" if is_sqlite
        else "array_to_string(COALESCE(o.tags, ARRAY[]::text[]), ' ')"
    )
    # ВАЖНО: в SQLite встроенные lower()/LIKE не понимают кириллицу —
    # регистронезависимость обеспечивает UDF-функция ILIKE(pattern, value),
    # зарегистрированная в app.db._register_sqlite_ilike. Аргументы:
    # сначала шаблон, потом проверяемое значение (в отличие от оператора).
    if is_sqlite:
        conds = " OR ".join(
            f"(ILIKE('%' || :w{i} || '%', o.title)"
            f" OR ILIKE('%' || :w{i} || '%', COALESCE(o.description, ''))"
            f" OR ILIKE('%' || :w{i} || '%', {tags_expr}))"
            for i in range(len(words))
        )
        order_expr = f"ILIKE('%' || :w0 || '%', {tags_expr})"
    else:
        conds = " OR ".join(
            f"(o.title LIKE '%' || :w{i} || '%'"
            f" OR COALESCE(o.description, '') LIKE '%' || :w{i} || '%'"
            f" OR {tags_expr} LIKE '%' || :w{i} || '%')"
            for i in range(len(words))
        )
        order_expr = f"{tags_expr} LIKE '%' || :w0 || '%'"
    stmt = sql_text(
        f"""
        SELECT o.id, o.title, COALESCE(o.description, '') AS descr,
               {tags_expr} AS tags_text
          FROM opportunities AS o
         WHERE o.status IN ('open', 'closing_soon')
           AND ({conds})
         ORDER BY CASE WHEN {order_expr} THEN 0 ELSE 1 END,
                  o.id ASC
         LIMIT 60
        """
    )
    params = {f"w{i}": w for i, w in enumerate(words)}
    rows = session.execute(stmt, params).fetchall()

    scored: dict[int, float] = {}
    for r in rows:
        title = (r.title or "").lower()
        descr = (r.descr or "").lower()
        tags = [t.strip() for t in re.split(r"[,\[\]\"']+", (r.tags_text or "").lower()) if t.strip()]
        score = 0.0
        for w in words:
            if any(w == t or fuzz.ratio(w, t) >= 80 for t in tags):
                score += 2.0
            elif w in title or any(fuzz.ratio(w, t) >= 80 for t in tags):
                score += 1.5
            elif w in title or fuzz.partial_ratio(w, title) >= 85:
                score += 1.0
            elif w in descr:
                score += 0.5
        if needle in title:
            score += 0.5
        if score >= MIN_SCORE:
            scored[r.id] = score
    if not scored:
        return []
    top_ids = sorted(scored, key=lambda i: (-scored[i], i))[:limit]
    objs = {
        o.id: o for o in session.query(Opportunity).filter(Opportunity.id.in_(top_ids))
    }
    results = [
        SearchResult(opportunity=objs[i], score=scored[i])
        for i in top_ids
        if i in objs
    ]
    logger.info("Деградированный поиск %r: принято=%s", needle, len(results))
    return results


def search(
    query: str,
    db: Session | None = None,
    *,
    limit: int = DEFAULT_LIMIT,
    engine: Engine | None = None,
) -> list[SearchResult]:
    """Ищет подходящие возможности по запросу на естественном языке.

    Args:
        query: текст запроса студента (например «хочу в проект по ИИ»).
        db: SQLAlchemy-сессия; если None — создаётся собственная.
        limit: максимальное число результатов (по умолчанию 5).
        engine: движок БД (по умолчанию — движок приложения).

    Returns:
        Список ``SearchResult`` (запись + скор), отсортированный по
        убыванию релевантности. Пустой список, если ничего не найдено,
        — это не ошибка.
    """
    cleaned = (query or "").strip().lower()
    if not cleaned:
        return []

    eng = engine or (db.get_bind() if db is not None else get_engine())
    own_session = db is None
    session = db if db is not None else Session(bind=eng)

    try:
        if eng.dialect.name != "postgresql" or not _pg_trgm_available(eng):
            logger.warning("pg_trgm недоступен — деградация к ILIKE-поиску")
            return _fallback_search(cleaned, session, limit)

        words = tokenize(cleaned)
        rows = session.execute(
            _SQL_SEARCH,
            {"query": cleaned, "words": words, "limit": limit},
        ).fetchall()

        scored_ids = [r.id for r in rows if float(r.score) >= MIN_SCORE]
        if not scored_ids:
            logger.info("Поиск %r: релевантных записей не найдено", cleaned)
            return []

        objs = {
            o.id: o
            for o in session.query(Opportunity).filter(
                Opportunity.id.in_(scored_ids)
            )
        }
        results = [
            SearchResult(opportunity=objs[r.id], score=float(r.score))
            for r in rows
            if r.id in objs
        ]
        logger.info(
            "Поиск %r: слов=%s, кандидатов=%s, принято=%s",
            cleaned, words, len(rows), len(results),
        )
        return results
    finally:
        if own_session:
            session.close()
