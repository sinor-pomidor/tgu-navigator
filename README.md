# ТГУ: Навигатор возможностей

ИИ-ассистент для студентов Томского государственного университета.

> 🚀 **Никогда не программировали?** Начните с файла
> **[START_HERE.md](START_HERE.md)** — там пошаговая инструкция: что установить,
> какие команды копировать по одной и как подключить Telegram-бота за 2 минуты.

Студент пишет запрос обычным языком (например: «Я учусь на Инноватике,
интересуюсь ИИ и хочу попасть в реальный проект»), а система находит в базе
проверенных университетских возможностей подходящие **проекты, лаборатории,
мероприятия и гранты** — с требованиями, сроками, контактами и ссылкой на
официальный источник.

Принцип работы: **Запрос → Поиск по базе → Рекомендации → Действие.**

Ключевое требование продукта: ответы опираются **только** на данные из базы
и сопровождаются источниками. Модель с нуля не обучается — используется
гибридный поиск по каталогу (pg_trgm + фильтры) и LLM-абстракция для
формулировки ответа (по умолчанию — mock-провайдер, работающий без ключей
и интернета).

## Статус проекта

Рабочий вертикальный срез (прототип для демонстрации):
каталог возможностей → гибридный поиск → ответ с подборкой и источниками →
доставка через REST API (`POST /ask`) и Telegram-бота. Все компоненты
реализованы и покрыты тестами (`pytest` зелёный).

## Технологии

- Python 3.11+, FastAPI + uvicorn
- PostgreSQL 16 с pgvector/pg_trgm (образ `pgvector/pgvector:pg16`, docker-compose)
- SQLAlchemy 2.x (синхронный режим), схема через `create_all` (без Alembic)
- aiogram 3.x — Telegram-бот
- pydantic-settings — конфигурация через `.env`
- pytest — тесты

## Быстрый старт

**Вариант 0 (самый простой):** установочный скрипт — делает всё ниже сам.
- Windows: дважды кликните `install.bat`
- Mac/Linux: `./install.sh`

```bash
# 1. Клонировать репозиторий, создать .env из примера (значения по умолчанию рабочие)
cp .env.example .env

# 2. Поднять PostgreSQL и приложение одной командой
docker compose up --build -d

# 3. Загрузить стартовый каталог возможностей
docker compose exec app python -m app.seed

# 4. Открыть интерфейс: http://localhost:8000/ (MVP-фронтенд)
#    API-документация: http://localhost:8000/docs, проверка живости: /health
curl -X POST http://localhost:8000/ask -H 'Content-Type: application/json' \
     -d '{"query": "хочу в проект по ИИ"}'
```

Вариант без Docker (локально, при доступном PostgreSQL):

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload        # API на :8000
python -m app.seed                   # загрузка каталога
python -m pytest                     # тесты
```

## Структура проекта

```
tgu-navigator/
├── .gitignore / .env.example   # гигиена репозитория и шаблон конфигурации
├── README.md                   # этот файл
├── requirements.txt            # зависимости
├── Dockerfile                  # образ приложения
├── docker-compose.yml          # db (PostgreSQL+pgvector) + app (FastAPI)
├── seed/opportunities.json     # стартовый каталог возможностей ТГУ
├── frontend/                   # MVP-фронтенд (статика, раздаётся с "/"):
│   ├── index.html              #   структура страницы
│   ├── style.css               #   стили
│   └── app.js                  #   логика чата и вызовы /ask, /opportunities
├── app/
│   ├── main.py                 # FastAPI-приложение, роутеры, lifespan
│   ├── config.py               # Settings из переменных окружения
│   ├── db.py                   # движок, сессии, init_db (create_all)
│   ├── models.py               # модель Opportunity (enum, теги, индексы)
│   ├── schemas.py              # Pydantic-схемы запросов/ответов
│   ├── seed.py                 # загрузка JSON-каталога в БД
│   ├── api/                    # health, CRUD каталога, POST /ask
│   ├── services/               # search (гибридный), answer (сборка ответа)
│   │   └── llm/                # base (интерфейс), mock, openai_compatible
│   └── bot/                    # Telegram-бот (aiogram 3): /start, текст
└── tests/                      # pytest: поиск + API (на реальном PostgreSQL)
```

## Переменные окружения (.env)

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `DATABASE_URL` | строка подключения к PostgreSQL | `postgresql+psycopg2://navigator:navigator@localhost:5432/navigator` |
| `LLM_PROVIDER` | `mock` или `openai_compatible` | `mock` (работает без сети и ключей) |
| `LLM_API_BASE` | база URL OpenAI-совместимого API | пусто |
| `LLM_API_KEY` | ключ API; пусто → mock | пусто |
| `LLM_MODEL` | название модели LLM | пусто |
| `TG_BOT_TOKEN` | токен бота от @BotFather | пусто (бот сообщит, как задать) |
| `APP_ENV` | `development` / `production` | `development` |

Файл `.env` никогда не коммитится (в `.gitignore`); в репозитории лежит
только `.env.example`.

## Как наполнять каталог

Два способа:

1. **JSON-сид** — отредактировать `seed/opportunities.json` и выполнить
   `python -m app.seed` (полная перезагрузка каталога, дубликаты исключены).
2. **REST API** — `POST /opportunities` через Swagger (`/docs`). Обязательны
   `title` и `source_url` (официальный источник); поля: `type`
   (project/lab/event/grant), `description`, `requirements`, `audience`,
   `tags`, `deadline`, `status` (open/closing_soon/closed), `contact`.

Правило качества данных: каждая возможность должна иметь рабочую ссылку на
официальный источник ТГУ — именно она попадает в поле `sources` ответа.

## Как запускать Telegram-бота

```bash
# 1. Получить токен у @BotFather в Telegram
# 2. Прописать TG_BOT_TOKEN=... в .env
python -m app.bot.bot
```

Бот отвечает на текстовые сообщения подборкой карточек (эмодзи типа,
название, срок, кнопка «Подробнее» со ссылкой на источник). Без токена
не падает — выводит понятную инструкцию в консоль.

## Основные эндпоинты

- `GET /` — MVP-фронтенд (чат с подборками, вызывается `POST /ask`)
- `GET /health` — проверка живости
- `GET/POST /opportunities`, `GET/PUT/DELETE /opportunities/{id}` — CRUD каталога
- `POST /ask {query}` — главный сценарий: поиск → подборка → структурированный
  JSON с полем `sources`
