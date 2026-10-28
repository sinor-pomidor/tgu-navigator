# База данных проекта «ТГУ: Навигатор возможностей» — структурная форма

Дополнение к основным инструкциям (раздел 5 ТЗ). Документ описывает **фактическую**
схему базы данных, правила целостности, индексы и различия двух режимов работы.
Актуален для ветки `main` начиная с v0.3.x.

## 1. Два режима работы БД (одна модель — две реализации)

| Режим | Когда включается | Движок | Особенности поиска |
|-------|------------------|--------|--------------------|
| **PostgreSQL 16 + pgvector + pg_trgm** | задан `DATABASE_URL=postgresql://...` (docker-compose или облачный Postgres) | SQLAlchemy 2.x, sync, psycopg2 | полноценный гибридный поиск: trigram-скоринг + теги + фильтры |
| **SQLite** (по умолчанию) | `DATABASE_URL` пуст | файл `data/navigator.db`, создаётся автоматически | деградированный ILIKE-скоринг; GIN/pg_trgm-конструкции пропускаются |

Публичный API (`app/services/search.py`, модели, схемы) в обоих режимах идентичен —
переключение не требует кода, только переменную окружения. Alembic не используется:
схема разворачивается `Base.metadata.create_all` при старте, недостающие колонки
добавляет идемпотентный `_ensure_ingest_columns` (аналог `app/migrations/add_origin_fields.py`).

## 2. Таблица `opportunities` (единственная на этапе прототипа)

| # | Поле | SQL-тип (PG / SQLite) | NULL | Default | Правила заполнения |
|---|------|------------------------|------|---------|--------------------|
| 1 | `id` | SERIAL / INTEGER PK | нет | автоинкремент | внешний ключ нигде не используется (таблица одна) |
| 2 | `type` | VARCHAR(10) + CHECK(`project`,`lab`,`event`,`grant`) | нет | — | обязателен; enum хранит **значения**, не имена |
| 3 | `title` | TEXT | нет | — | обязателен; trimming ответственность слоя ввода (API/импорт) |
| 4 | `description` | TEXT | да | NULL | основной текст; участвует в trigram-индексе |
| 5 | `requirements` | TEXT | да | NULL | требования к участнику; в поиск не входит (фильтр будущего) |
| 6 | `audience` | TEXT | да | NULL | для кого (курс/факультет); свободный текст |
| 7 | `tags` | JSON (`[]` если пусто) | нет | `[]` | список строк; нормализуется при чтении (мусор → `[]`); участвует в GIN-индексе (PG) и скоринге тегов |
| 8 | `deadline` | DATE | да | NULL | NULL = «без дедлайна» (постоянная возможность); влияет на `status` |
| 9 | `status` | VARCHAR(13) + CHECK(`open`,`closing_soon`,`closed`) | нет | `open` | вычисляется ядром `refresh_statuses` (см. п.5), руками ставится только через CRUD |
| 10 | `contact` | TEXT | да | NULL | e-mail/телефон/кабинет; валидация формата не требуется по ТЗ |
| 11 | `source_url` | TEXT | нет | — | **обязателен**: запись без официального источника в БД не попадает; должен начинаться с `http(s)://`; ключ дедупликации ingestion |
| 12 | `source` | TEXT | нет | `'manual'` | имя источника-парсера (`tsu_site`, `csv_import`, …); в паре с `external_id` образует естественный ключ parsed-записей |
| 13 | `origin` | VARCHAR(6) + CHECK(`manual`,`parsed`) | нет | `manual` | `manual` — человек (seed/CRUD/кураторский CSV); `parsed` — конвейер. Парсер **никогда** не трогает manual-записи |
| 14 | `last_seen_at` | TIMESTAMPTZ / TIMESTAMP | да | NULL | когда источник последний раз подтверждал запись; обновляется каждым прогоном ingestion |
| 15 | `external_id` | TEXT | да | NULL | id записи на стороне источника; уникален в рамках `source` для origin=`parsed` (частичный индекс, см. п.4) |
| 16 | `created_at` | TIMESTAMPTZ | нет | now() | серверное значение |
| 17 | `updated_at` | TIMESTAMPTZ | нет | now() ON UPDATE | ORM `onupdate` + серверный default |

Модель: `app/models.py::Opportunity`. Pydantic-схемы API: `app/schemas.py`.

## 3. Продуктовые правила целостности (кто их обеспечивает)

| Правило из ТЗ | Где обеспечивается |
|---------------|--------------------|
| Без `source_url` запись не попадает в БД | NOT NULL в модели + валидация `normalize.validate_raw` (пусто/не-URL → отбраковка) + проверка `csv_import` + схема `OpportunityCreate` |
| Дедупликация при загрузке по `source_url` | `normalize.upsert_opportunity` (parsed): существующая manual-запись с тем же URL **не перезаписывается**; parsed-запись обновляется на месте |
| Дедупликация CSV-импорта | `csv_import.import_events`: внутри файла и среди manual-записей того же `source` — по нормализованному URL (lower/strip/trailing `/`) |
| Manual-записи парсер не трогает | все ветки upsert/delete-stale проверяют `origin == 'parsed'` |
| Статусы по дедлайну | ядро `normalize.refresh_statuses` (см. п.5); вызывается после каждого прогона ingestion и при старте приложения |
| Enum-поля ограничены значениями | CHECK-ограничения (`native_enum=False`) работают и на PG, и на SQLite |

Норма URL для сравнения: strip → lower → убрать один завершающий `/`
(реализовано одинаково в `normalize._norm_url` и `csv_import._norm_url`).

## 4. Индексы

Создаются автоматически `init_db()`; специфичные для PostgreSQL добавляются
только на Postgres (`Opportunity.postgres_only_indexes()`).

| Имя | Колонки | Тип | Назначение |
|-----|---------|-----|-----------|
| (PK) | `id` | btree | первичный ключ |
| `ix_opportunities_type_status` | `(type, status)` | btree, **обе БД** | фильтр «живые возможности данного типа» — самый частый предикат поиска |
| `ix_opportunities_source_url` | `source_url` | btree, **обе БД** | быстрый поиск дубликата при upsert |
| `ix_opportunities_deadline` | `deadline` | btree, **обе БД** | выборки по срокам, автообновление статусов |
| `ix_opportunities_title_trgm` | `title` | GIN + gin_trgm_ops (PG) | полнотекстовый trigram-поиск по названию |
| `ix_opportunities_description_trgm` | `description` | GIN + gin_trgm_ops (PG) | trigram-поиск по описанию |
| `ix_opportunities_tags_gin` | `tags` | GIN (PG) | совпадения слов запроса с тегами |
| `uq_opportunities_source_external` | `(source, external_id)` WHERE `origin='parsed' AND external_id IS NOT NULL` | частичный UNIQUE (PG) | жёсткая гарантия: один прогон не создаёт двойник одной и той же страницы источника |

На SQLite роль последних четырёх выполняет деградированный ILIKE-скоринг —
результаты сопоставимы по качеству на малых объёмах (до ~10³ записей).

## 5. Жизненный цикл записи (структурная «форма»)

```
        [seed/opportunities.json]   [CRUD POST /opportunities]   [CSV куратора]
                     │                        │                         │
                     └────────────┬───────────┴─────────────┬───────────┘
                                  ▼                         ▼
                        origin='manual'            origin='manual', type='event'
                                  │                         │
   [парсер сайта ТГУ → RawItem → normalize]                 │
                                  ▼                         │
                        origin='parsed' ◄── upsert по source_url / (source, external_id)
                                  │                         │
                    refresh_statuses (после прогона и при старте)
                                  ▼
        deadline < сегодня → closed
        deadline ≤ +3 дня   → closing_soon
        иначе               → open
                                  │
                    last_seen_at обновляется каждым прогоном;
                    запись, не подтверждённая источником N прогонов, —
                    кандидат на удаление (правило включается в эксплуатации)
```

## 6. Задел под следующие этапы (структура готова, но пока не задействована)

* **Векторный поиск (pgvector).** Образ БД уже `pgvector/pgvector:pg16`. План:
  добавить таблицу `opportunity_embeddings(opportunity_id FK, embedding vector(768),
  model_version)` + HNSW-индекс — тяжёлые данные не замедляют основную таблицу.
  Расширение `vector` будет создано в `init_db` рядом с `pg_trgm`.
* **История изменений.** Возможна таблица `opportunity_events(opportunity_id, kind,
  data jsonb, created_at)` для аудита парсинга (что/когда менялось) — решение
  принимается при переходе к эксплуатации.
* **Справочник источников.** Сейчас `source` — свободная строка; при росте числа
  парсеров переезжает в таблицу `sources(name, base_url, parser, enabled)`.

## 7. Как проверить схему своими руками

```bash
# SQLite-режим (по умолчанию):
python -c "from app.db import init_db, get_engine; init_db(); \
eng=get_engine(); \
print([r[0] for r in eng.exec_driver_sql(\"SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='opportunities'\")])"

# PostgreSQL-режим (docker compose up -d db, DATABASE_URL в .env):
psql "$DATABASE_URL" -c "\d opportunities" -c "SELECT indexname FROM pg_indexes WHERE tablename='opportunities';"
```
