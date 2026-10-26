"""Источник «публичные страницы сайта ТГУ».

Собирает анонсы мероприятий со стартовых URL (``INGEST_START_URLS``):
со списка новостей/анонсов берёт ссылки на подробности, из карточки
мероприятия извлекает заголовок, описание, дату и теги.

Особенности этапа 1:
* Селекторы написаны «защитно» — несколько эвристик вместо жёсткой
  привязки к вёрстке; если структура страницы изменится, источник
  вернёт пустой список, а не упадёт (конвейер зафиксирует это в отчёте).
* Вежливость к сайту: задержка между запросами (``INGEST_DELAY_SECONDS``),
  честный User-Agent, максимум страниц за прогон.
* На этапе 2 сюда же подключаются VK API / Telegram-каналы как отдельные
  классы-наследники ``BaseSource`` — конвейер менять не нужно.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.ingest.base import BaseSource, RawItem

logger = logging.getLogger(__name__)

#: Сколько страниц списка обработать за один прогон.
MAX_LIST_PAGES = 3
#: Сколько карточек мероприятий собрать за прогон (страховка от разрастания).
MAX_ITEMS_PER_RUN = 60

#: Известные разделы карточек на сайтах ТГУ (news.tsu.ru, vestnik.tsu.ru).
ARTICLE_SECTIONS = {
    "calendar-of-events", "news", "projects", "announce", "science", "events",
}

#: Служебные страницы-списки, которые нельзя принимать за мероприятия.
LISTING_SLUGS = {
    "index.php", "rss.php", "search", "media", "archive-information-materials",
    "calendar-of-events", "news", "projects", "announce",
}

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "мая": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11,
    "декабр": 12,
}


def parse_russian_date(text: str | None) -> date | None:
    """Пытается вытащить первую дату из текста («15 ноября 2026», «15.11.2026»).

    Returns:
        ``date`` либо None, если дата не распознана.
    """
    if not text:
        return None
    value = text.replace("\xa0", " ")

    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    m = re.search(
        r"(\d{1,2})\s*(?:[-–—]\s*\d{1,2}\s*)?("
        r"январ\w*|феврал\w*|март\w*|апрел\w*|мая|июн\w*|июл\w*|август\w*|"
        r"сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)"
        r"\s*(\d{4})?",
        value,
        flags=re.IGNORECASE,
    )
    if m:
        day = int(m.group(1))
        month_root = m.group(2).lower()
        month = next((v for k, v in _MONTHS.items() if month_root.startswith(k)), None)
        year = int(m.group(3)) if m.group(3) else date.today().year
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    return None


#: Ключевые слова для определения типа возможности по тексту карточки.
_GRANT_WORDS = ("грант", "стипенди", "президиум", "финансировани",
                "фонд содействия")
_PROJECT_WORDS = ("научный проект", "исследовательский проект", "лаборатория",
                  "открыт прием", "прием заявок", "конкурс проектов",
                  "программа поддержки")
_CONFERENCE_WORDS = ("конференц", "семинар", "симпозиум", "форум", "школа",
                     "конгресс", "съезд", "вебинар", "лекторий", "лекция",
                     "круглый стол", "чтения", "хакатон", "мастер-класс")


def guess_type(title: str, description: str) -> str:
    """Определяет тип возможности (grant/project/event) по тексту карточки.

    Прототипная эвристика: сначала распознаются гранты и научные проекты
    (по устойчивым формулировкам), затем конференции/семинары — это события;
    всё остальное тоже считаем мероприятиями.
    """
    blob = f"{title} {description}".lower()
    if any(w in blob for w in _GRANT_WORDS):
        return "grant"
    if any(w in blob for w in _PROJECT_WORDS):
        return "project"
    if any(w in blob for w in _CONFERENCE_WORDS):
        return "event"
    # «Исследовательск*» без явного слова «проект» — всё же исследовательское
    # мероприятие, но не проект; проект засчитываем только по точным фразам.
    return "event"


class TsuSiteSource(BaseSource):
    """Сбор анонсов мероприятий с публичных страниц tsu.ru."""

    name = "tsu_site"

    def __init__(self, start_urls: list[str] | None = None) -> None:
        settings = get_settings()
        self.start_urls = start_urls or settings.ingest_start_urls
        self.delay = settings.ingest_delay_seconds
        self._client = httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "TguNavigatorBot/0.1 (+https://github.com/sinor-pomidor/"
                    "tgu-navigator; prototype data collector)"
                ),
                "Accept-Language": "ru,en;q=0.8",
            },
        )

    # -------------------------- public API ----------------------------

    def fetch(self) -> list[RawItem]:
        """Собирает карточки мероприятий со всех стартовых страниц.

        Ошибки сети по одной странице не прерывают прогон — страница
        пропускается, ошибка попадает в лог.
        """
        items: list[RawItem] = []
        seen_links: set[str] = set()
        for url in self.start_urls[:MAX_LIST_PAGES]:
            try:
                detail_links = self._collect_detail_links(url, seen_links)
            except Exception as exc:  # noqa: BLE001 - сеть недоступна?
                logger.warning("Страница %s недоступна: %s", url, exc)
                continue
            for link in detail_links:
                if len(items) >= MAX_ITEMS_PER_RUN:
                    return items
                try:
                    item = self._parse_detail(link)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Карточка %s не разобрана: %s", link, exc)
                    continue
                if item is not None:
                    items.append(item)
                time.sleep(self.delay)
        return items

    # -------------------------- internals -----------------------------

    def _get(self, url: str) -> httpx.Response:
        response = self._client.get(url)
        response.raise_for_status()
        return response

    def _collect_detail_links(self, list_url: str, seen: set[str]) -> list[str]:
        """Вытаскивает из страницы списка ссылки на материалы внутри tsu.ru.

        Структура разделов ТГУ меняется, поэтому распознавание карточек
        строится на нескольких эвристиках:
        * односегментные относительные ссылки вида ``/solas/`` — карточки
          конференций и анонсов на vestnik.tsu.ru;
        * многоуровневые пути с датой/числовым сегментом (``/news/2026/...``)
          или в известных разделах (news, announce, science, events);
        * у ссылки должен быть осмысленный анкорный текст.
        """
        html = self._get(list_url).text
        soup = BeautifulSoup(html, "lxml")
        host = httpx.URL(list_url).host.lower()
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(list_url, a["href"]).split("#", 1)[0].split("?", 1)[0]
            if href in seen or href.rstrip("/") == list_url.rstrip("/"):
                continue
            parsed = httpx.URL(href)
            if parsed.host.lower() != host and not parsed.host.lower().endswith(".tsu.ru"):
                continue
            path = parsed.path.strip("/")
            if not path:
                continue
            parts = path.split("/")
            # Разделы-списки сами по себе не карточки материалов.
            if parts[-1] in LISTING_SLUGS:
                continue
            looks_like_article = (
                len(parts) == 1 and re.fullmatch(r"[a-z0-9_-]{4,40}", parts[0]) is not None
                or len(parts) >= 3
                and (parts[0] in ARTICLE_SECTIONS
                     or any(seg.isdigit() and len(seg) == 4 for seg in parts[1:]))
            )
            if not looks_like_article:
                continue
            text_ = a.get_text(" ", strip=True)
            if len(text_) < 15:  # навигационные ссылки без осмысленного текста
                continue
            seen.add(href)
            links.append(href)
            if len(links) >= MAX_ITEMS_PER_RUN:
                break
        return links

    def _parse_detail(self, url: str) -> RawItem | None:
        """Разбирает страницу карточки мероприятия в RawItem (или None)."""
        html = self._get(url).text
        soup = BeautifulSoup(html, "lxml")

        # Страницы-ошибки («404», «страница не найдена») пропускаем молча.
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and "404" in (og_title.get("content") or ""):
            return None

        title_tag = soup.find(["h1"])
        title = title_tag.get_text(" ", strip=True) if title_tag else None
        if not title or len(title) < 5 or "не найдена" in title.lower():
            return None

        description = self._extract_description(soup)
        event_date = self._extract_date(soup, url)
        tags = self._extract_tags(soup)

        # external_id — стабильный хеш домена+пути: повторный забор того же
        # материала обновит запись, а не создаст дубль.
        parsed = httpx.URL(url)
        path = f"{parsed.host}{parsed.path}"
        external_id = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]

        item_type = guess_type(title, description or "")

        return RawItem(
            title=title,
            source_url=url,
            external_id=external_id,
            type=item_type,
            description=description,
            tags=tags,
            deadline=event_date,
            source_name=self.name,
        )

    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> str | None:
        """Первый содержательный абзац после заголовка."""
        h1 = soup.find("h1")
        node = h1.find_next("p") if h1 else soup.find("p")
        while node is not None:
            text_ = node.get_text(" ", strip=True)
            if len(text_) >= 40:
                return re.sub(r"\s+", " ", text_)[:1500]
            node = node.find_next("p")
        return None

    @staticmethod
    def _extract_date(soup: BeautifulSoup, url: str) -> date | None:
        """Ищет дату в тексте страницы, затем в URL (частый формат /2026/11/15/)."""
        body_text = soup.get_text(" ", strip=True)[:6000]
        parsed = parse_russian_date(body_text)
        if parsed:
            return parsed
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
        if m:
            try:
                url_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
            # Год в URL доверяем только если дата не в прошлом: иначе
            # архивные страницы дадут ложный дедлайн.
            return url_date if url_date >= date.today() else None
        return None

    @staticmethod
    def _extract_tags(soup: BeautifulSoup) -> list[str]:
        """Теги/рубрики страницы: метатеги keywords и подписи рубрик."""
        tags: list[str] = []
        meta = soup.find("meta", attrs={"name": "keywords"})
        if meta and meta.get("content"):
            tags += [t.strip() for t in meta["content"].split(",") if len(t.strip()) > 2]
        for a in soup.select("a[href*='/search'], .tag, .rubric"):
            text_ = a.get_text(" ", strip=True)
            if 2 < len(text_) <= 30 and text_.lower() not in {t.lower() for t in tags}:
                tags.append(text_)
        return tags[:8]
