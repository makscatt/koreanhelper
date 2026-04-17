#!/usr/bin/env python3
"""
Gemini News Bot — Корейский шоубиз
Автопостинг лучших новостей (8+/10) с фото в @KoreanMaks каждые 4 часа.
Работает ВНУТРИ Flask-приложения на Render.

Подключение: в app.py добавить:  import bot
"""

import os
import re
import json
import hashlib
import logging
import sqlite3
import threading
import time
import datetime

import feedparser
import requests
import google.generativeai as genai

# ============================================================
# НАСТРОЙКИ
# ============================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CHANNEL_USERNAME = "@KoreanMaks"
CHANNEL_LINK = "https://t.me/KoreanMaks"
GEMINI_MODEL = "gemini-3.1-pro-preview"
NEWS_PER_FEED = 10
TG_MAX_LENGTH = 4000
TOPICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "published_topics.json")
MAX_SAVED_TOPICS = 50

# БД бота на persistent disk Render (тот же диск, что у основного SQLite Flask-приложения).
# Локально, если /var/data недоступен — пишем рядом с bot.py.
_DEFAULT_DB_DIR = "/var/data"
if os.path.isdir(_DEFAULT_DB_DIR) and os.access(_DEFAULT_DB_DIR, os.W_OK):
    BOT_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "bot.db")
else:
    BOT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")

# ============================================================
# СОСТОЯНИЕ (только кэш в памяти — всё персистентное живёт в SQLite)
# ============================================================

_state = {
    "news_cache": {},
    "digest_list": [],
    "last_post_text": "",
    "last_post_nid": "",
}

_db_lock = threading.Lock()

# ============================================================
# RSS-ИСТОЧНИКИ (только корейский шоубиз)
# ============================================================

FEEDS = {
    "korean": {
        "label": "🇰🇷 КОРЕЙСКИЙ ШОУБИЗ",
        "feeds": [
            "https://www.soompi.com/feed",
            "https://www.koreaboo.com/feed",
            "https://www.kpopstarz.com/rss/archives/all.xml",
            "https://dramabeans.com/feed",
            "https://www.scmp.com/rss/507633/feed",
            "https://en.yna.co.kr/RSS/news.xml",
            "https://www.koreaherald.com/rss/kpop",
            "https://www.allkpop.com/rss",
        ],
        "topic_filter": """
Корейская индустрия развлечений.

ОЦЕНИВАЙ ПО ШКАЛЕ 1-10. Оставляй ТОЛЬКО 8-10 баллов.

ЧТО ЦЕННО (8-10 баллов):
- Новости про BTS, BLACKPINK, Stray Kids, SEVENTEEN, aespa, NewJeans и другие топовые группы (камбэки, рекорды, скандалы, мировые туры)
- Топовые актёры: Чжи Чан Ук, Ви Ха Джун, Ли Джун Ги, Сон Джун Ки, Пак Со Джун, Чон Джи Хён, Хан Со Хи, Ким Су Хён — любые новости про них
- Крупные премьеры дорам и корейских фильмов с известным кастом
- Скандалы и резонансные события (уход из группы, судебные дела, неожиданные камбэки)
- Рекорды на Billboard, Grammy, мировые чарты
- Корейское кино на международных фестивалях (Канны, Оскар, Венеция)

ЧТО МУСОР (1-7 баллов, ВЫКИДЫВАЙ):
- Малоизвестные айдолы без широкой аудитории
- Рутинные фанмитинги и мелкие ивенты
- Фандомные склоки без реального инфоповода
- Мелкие обновления без новостной ценности

АНТИКЛИКБЕЙТ-ФИЛЬТР:
- Если новость обещает «раскрыть причину» / «шокирующие подробности» / «настоящую правду», но в тексте НЕТ конкретики — это кликбейт, ставь 1 балл.
- Если суть новости сводится к «кто-то намекнул на что-то в соцсетях» без деталей — ставь 1-3 балла.
- Новость ДОЛЖНА содержать конкретный факт: что произошло, кто, когда, какой результат.
""",
    },
}

# ============================================================
# ПРОМПТ ДЛЯ ПОСТА
# ============================================================

POST_PROMPT = """
Ты — автор Telegram-канала. Пишешь живо, понятно, с лёгким юмором. Твоя суперсила — объяснять сложное простыми словами.

Напиши пост на основе этой новости:

Заголовок: {title}
Описание: {description}
Есть фото к посту: {has_photo}

СТИЛЬ И ТОН:
- Простая, живая речь. Как будто рассказываешь другу за чаем — без сленга, без умных слов, без канцелярита.
- ЗАПРЕЩЁН сленг и жаргон: «пофиксить», «баг», «фичи», «морока», «жёстко», «чувак», «безумный», «мощный», «краш», «вайб», «кринж», «имба». Пиши так, чтобы понял и подросток, и бабушка.
- Юмор — да, но мягкий и понятный. Не натужный.
- Последняя строка может быть коротким остроумным послесловием (1-5 слов) — но ТОЛЬКО если получилось действительно удачно. Лучше без неё, чем плохая.

ФОРМАТ:
1 строка: один эмодзи + заголовок (до 60 символов). Заголовок передаёт СУТЬ, а не интригует.
2-5 строк: раскрытие новости. Конкретика: имена, цифры, даты, детали. Каждое предложение несёт новую информацию.

АНТИКЛИКБЕЙТ:
- Если в исходнике нет конкретных фактов — НЕ ДОДУМЫВАЙ. Лучше короткий пост с фактами, чем длинный с водой.
- ЗАПРЕЩЕНО: «стало известно что...», «оказалось что...», «утверждается что...» без раскрытия ЧТО ИМЕННО.
- ЗАПРЕЩЕНО: «спровоцировал волну», «вызвал бурную реакцию», «не ограничивается официальным заявлением» — это пустышки.
- Если новость — чистый кликбейт без содержания, напиши «SKIP» и ничего больше.

ВАЖНО: если к посту НЕТ фото — НЕ пиши про «кадры», «фото», «скриншоты», «первые изображения». Фокус на фактах.

ПРАВИЛА:
1. На русском языке. 200-500 символов.
2. Чистый текст, без HTML. Без хештегов.
3. Без призывов и вопросов читателям.
4. Без «Подписаться» — добавится автоматически.
5. Один эмодзи только в заголовке.
6. НЕ добавляй ссылку на оригинал.
"""

# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("newsbot")

# ============================================================
# TELEGRAM API
# ============================================================

def tg_api(method: str, payload: dict):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            logger.error(f"TG {method} {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as e:
        logger.error(f"TG {method} error: {e}")
        return None


def tg_send(text: str, reply_markup: dict = None, chat_id: str = None):
    cid = chat_id or TELEGRAM_CHAT_ID
    chunks = []
    if len(text) <= TG_MAX_LENGTH:
        chunks = [text]
    else:
        parts = text.split("\n\n")
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 > TG_MAX_LENGTH:
                if current: chunks.append(current.strip())
                current = part
            else:
                current += "\n\n" + part if current else part
        if current: chunks.append(current.strip())

    for i, chunk in enumerate(chunks):
        payload = {"chat_id": cid, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        tg_api("sendMessage", payload)
        if i < len(chunks) - 1: time.sleep(0.5)


def tg_send_photo(photo_url: str, caption: str, reply_markup: dict = None, chat_id: str = None):
    cid = chat_id or TELEGRAM_CHAT_ID
    if len(caption) > 1024: caption = caption[:1020] + "..."
    payload = {"chat_id": cid, "photo": photo_url, "caption": caption, "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    result = tg_api("sendPhoto", payload)
    if not result or not result.get("ok"):
        logger.warning("sendPhoto failed, fallback to text")
        tg_send(caption, reply_markup=reply_markup, chat_id=chat_id)
    return result


# ============================================================
# УТИЛИТЫ
# ============================================================

def _news_id(title: str, link: str) -> str:
    return hashlib.md5(f"{title}|{link}".encode()).hexdigest()[:12]

def _interval_text(s: int) -> str:
    h = s / 3600
    if h == int(h):
        h = int(h)
        return "1 час" if h == 1 else f"{h} часа" if h < 5 else f"{h} часов"
    return f"{h} часа"


def _find_image_for(nid: str) -> str:
    """Ищет фото для новости. Сначала в самой записи, потом по похожим заголовкам в кэше."""
    item = _state["news_cache"].get(nid, {})
    if item.get("image"):
        return item["image"]

    title = item.get("title", "").lower()
    if not title:
        return ""

    keywords = [w for w in re.split(r'\W+', title) if len(w) > 4]
    if not keywords:
        return ""

    best_match = ""
    best_score = 0

    for other_id, other in _state["news_cache"].items():
        if other_id == nid or not other.get("image"):
            continue
        other_title = other.get("title", "").lower()
        score = sum(1 for kw in keywords if kw in other_title)
        if score > best_score and score >= 2:
            best_score = score
            best_match = other["image"]

    return best_match

def _extract_image(entry) -> str:
    media = entry.get("media_content", [])
    if media:
        for m in media:
            url = m.get("url", "")
            if url and any(ext in url for ext in ("jpg", "jpeg", "png", "webp")):
                return url
        if media[0].get("url"): return media[0]["url"]
    thumb = entry.get("media_thumbnail", [])
    if thumb and thumb[0].get("url"): return thumb[0]["url"]
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image"):
            return enc.get("href", "") or enc.get("url", "")
    content = entry.get("content", [{}])
    html = entry.get("description", "") or ""
    if content and isinstance(content, list): html = content[0].get("value", html)
    img = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    if img:
        url = img.group(1)
        if "gravatar" not in url and "pixel" not in url and "1x1" not in url: return url
    return ""


# ============================================================
# ИСТОРИЯ ОПУБЛИКОВАННЫХ ТЕМ (SQLite — persistent disk Render)
# ============================================================

def _db():
    """Открывает соединение. Каждый вызов — своё соединение (безопасно для потоков)."""
    conn = sqlite3.connect(BOT_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """Создаёт таблицы при первом старте. Идемпотентно."""
    with _db_lock, _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_news (
                nid      TEXT PRIMARY KEY,
                headline TEXT NOT NULL,
                summary  TEXT DEFAULT '',
                ts       TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_kv (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
    logger.info(f"💾 Bot DB ready: {BOT_DB_PATH}")


def _kv_get(key: str, default=None):
    with _db_lock, _db() as conn:
        row = conn.execute("SELECT value FROM bot_kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _kv_set(key: str, value):
    with _db_lock, _db() as conn:
        conn.execute(
            "INSERT INTO bot_kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()


def _is_sent(nid: str) -> bool:
    with _db_lock, _db() as conn:
        row = conn.execute("SELECT 1 FROM sent_news WHERE nid = ?", (nid,)).fetchone()
    return row is not None


def _load_published_topics() -> list:
    """Возвращает последние MAX_SAVED_TOPICS опубликованных тем (для промпта Gemini)."""
    try:
        with _db_lock, _db() as conn:
            rows = conn.execute(
                "SELECT headline, summary, ts FROM sent_news ORDER BY ts DESC LIMIT ?",
                (MAX_SAVED_TOPICS,),
            ).fetchall()
        # Возвращаем в хронологическом порядке (старые → новые), как было в старом JSON
        return [dict(r) for r in reversed(rows)]
    except Exception as e:
        logger.error(f"Load topics error: {e}")
        return []


def _save_published_topic(nid: str, headline: str, summary: str = ""):
    """Сохраняет факт публикации: и сам nid (чтобы не постить повторно),
    и тему (чтобы Gemini не предлагал похожие)."""
    try:
        with _db_lock, _db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sent_news(nid, headline, summary, ts) VALUES(?, ?, ?, ?)",
                (nid, headline, summary, datetime.datetime.now().isoformat()),
            )
            conn.commit()
        logger.info(f"📝 Сохранено в БД: {headline[:50]}")
    except Exception as e:
        logger.error(f"Save topic error: {e}")


def _migrate_json_to_db():
    """Одноразовая миграция старого published_topics.json в БД при первом запуске после апдейта.
    После успешной миграции файл переименовывается в .migrated, чтобы не повторяться."""
    if not os.path.exists(TOPICS_FILE):
        return
    try:
        with open(TOPICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            return

        migrated = 0
        with _db_lock, _db() as conn:
            for t in data:
                headline = (t.get("headline") or "").strip()
                if not headline:
                    continue
                summary = t.get("summary", "") or ""
                ts = t.get("ts") or datetime.datetime.now().isoformat()
                # В старом JSON не было nid — генерим синтетический по headline
                nid = "json_" + hashlib.md5(headline.encode()).hexdigest()[:12]
                conn.execute(
                    "INSERT OR IGNORE INTO sent_news(nid, headline, summary, ts) VALUES(?, ?, ?, ?)",
                    (nid, headline, summary, ts),
                )
                migrated += 1
            conn.commit()

        try:
            os.rename(TOPICS_FILE, TOPICS_FILE + ".migrated")
        except Exception:
            pass
        logger.info(f"📦 Мигрировано из JSON в БД: {migrated} тем")
    except Exception as e:
        logger.error(f"Migrate JSON error: {e}")


# ============================================================
# НАСТРОЙКИ С ПЕРСИСТЕНТНОСТЬЮ (interval, last_publish_time)
# ============================================================

def _get_interval() -> int:
    """Интервал в секундах. По умолчанию 12 часов."""
    raw = _kv_get("interval", None)
    try:
        return int(raw) if raw is not None else 12 * 60 * 60
    except (TypeError, ValueError):
        return 12 * 60 * 60


def _set_interval(seconds: int):
    _kv_set("interval", int(seconds))


def _get_last_publish_time() -> float:
    raw = _kv_get("last_publish_time", None)
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _set_last_publish_time(ts: float):
    _kv_set("last_publish_time", float(ts))


# ============================================================
# GEMINI — ДЕДУПЛИКАЦИЯ ЗАГОЛОВКОВ (Слой 1 — на этапе парсинга)
# ============================================================

def gemini_dedup_titles(items: list) -> list:
    """Группирует новости по темам через Gemini (только заголовки — дёшево).
    Из каждой группы оставляет одну лучшую новость (с фото и длинным описанием).
    Возвращает дедуплицированный список items."""

    if len(items) <= 3:
        return items

    # Формируем список заголовков с ID
    titles_text = ""
    for item in items:
        titles_text += f"[{item['id']}] {item['title']}\n"

    prompt = f"""Ты — редактор. Перед тобой список заголовков новостей из РАЗНЫХ источников.
Многие описывают ОДНО И ТО ЖЕ событие разными словами.

ЗАДАЧА: сгруппируй заголовки по ТЕМАМ (одно событие = одна группа).
Заголовки об одном и том же событии, человеке, релизе, скандале — это одна группа, даже если сформулированы по-разному.

ВЕРНИ СТРОГО JSON (без markdown, без ```):
[
  {{
    "topic": "Краткое описание темы (5-10 слов)",
    "ids": ["id1", "id2", "id3"]
  }}
]

Если заголовок уникальный (нет дублей) — он тоже должен быть в списке как группа с одним id.

ЗАГОЛОВКИ:
{titles_text}"""

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        groups = json.loads(text) if text.startswith("[") else []
    except Exception as e:
        logger.error(f"Gemini dedup error: {e}")
        return items  # При ошибке — возвращаем как есть

    if not groups:
        return items

    # Строим индекс items по id
    items_by_id = {item["id"]: item for item in items}

    # Из каждой группы выбираем лучшую новость
    deduped = []
    seen_ids = set()

    for group in groups:
        group_ids = group.get("ids", [])
        topic = group.get("topic", "")

        # Собираем реальные items этой группы
        group_items = [items_by_id[gid] for gid in group_ids if gid in items_by_id]
        if not group_items:
            continue

        if len(group_items) > 1:
            logger.info(f"🔗 Дубли объединены ({len(group_items)} шт): {topic}")

        # Выбираем лучшую: приоритет — есть фото + длинное описание
        best = max(group_items, key=lambda x: (
            bool(x.get("image")),          # с фото лучше
            len(x.get("description", "")), # длинное описание лучше
        ))

        # Если у лучшей нет фото, но у другой в группе есть — забираем фото
        if not best.get("image"):
            for gi in group_items:
                if gi.get("image"):
                    best["image"] = gi["image"]
                    break

        if best["id"] not in seen_ids:
            deduped.append(best)
            seen_ids.add(best["id"])

    # Добавляем items, которые Gemini не упомянул (на всякий случай)
    for item in items:
        if item["id"] not in seen_ids:
            deduped.append(item)
            seen_ids.add(item["id"])

    logger.info(f"📊 Дедупликация: {len(items)} → {len(deduped)} новостей")
    return deduped


# ============================================================
# ПАРСИНГ RSS
# ============================================================

def fetch_news(feeds: list, section: str) -> list:
    items = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                logger.warning(f"Parse failed: {url}"); continue
            source = feed.feed.get("title", url)
            for entry in feed.entries[:NEWS_PER_FEED]:
                title = entry.get("title", "").strip()
                desc = entry.get("description", "").strip()
                link = entry.get("link", "").strip()
                image = _extract_image(entry)
                desc_clean = re.sub(r"<[^>]+>", "", desc)
                if len(desc_clean) > 500: desc_clean = desc_clean[:500] + "..."
                nid = _news_id(title, link)
                item = {"id": nid, "title": title, "description": desc_clean,
                        "link": link, "source": source, "section": section, "image": image}
                existing = _state["news_cache"].get(nid)
                if existing and not existing.get("image") and image:
                    existing["image"] = image
                _state["news_cache"][nid] = item
                items.append(item)
        except Exception as e:
            logger.error(f"RSS error {url}: {e}")
    logger.info(f"[{section}] Fetched: {len(items)}")
    return items


# ============================================================
# GEMINI — ФИЛЬТРАЦИЯ С ОЦЕНКАМИ
# ============================================================

def gemini_digest(news_items: list, topic_filter: str) -> list:
    news_text = ""
    for item in news_items:
        news_text += (
            f"[ID: {item['id']}]\n"
            f"Источник: {item['source']}\n"
            f"Заголовок: {item['title']}\n"
            f"Описание: {item['description']}\n"
            f"Ссылка: {item['link']}\n\n"
        )

    # Слой 2: загружаем историю опубликованных тем
    published_topics = _load_published_topics()
    already_published_text = ""
    if published_topics:
        already_published_text = "\n\nУЖЕ ОПУБЛИКОВАННЫЕ ТЕМЫ (НЕ ПРЕДЛАГАЙ ПОХОЖИЕ):\n"
        for t in published_topics[-30:]:  # последние 30 тем
            already_published_text += f"- {t['headline']}\n"
        already_published_text += "\nЕсли новость описывает ТО ЖЕ событие/тему что уже опубликована — ВЫКИДЫВАЙ, даже если есть новые детали.\n"

    prompt = f"""
Ты — строгий редактор новостного канала. Твоя задача — отобрать ТОЛЬКО по-настоящему важные и резонансные новости.

ТЕМАТИКА И КРИТЕРИИ ОЦЕНКИ:
{topic_filter}

ЖЁСТКОЕ ПРАВИЛО ДЕДУПЛИКАЦИИ:
Если несколько новостей описывают ОДНО И ТО ЖЕ событие (даже если из разных источников, разными словами, с разных углов) — это ДУБЛИ.
Оставляй ТОЛЬКО ОДНУ — ту, где больше конкретики и деталей. Остальные дубли ВЫКИДЫВАЙ полностью.
{already_published_text}
ИНСТРУКЦИЯ:
1. Сначала найди и удали все дубли (оставь только лучший вариант каждого события).
2. Оцени КАЖДУЮ оставшуюся новость по шкале 1-10.
3. ВЫКИНЬ всё что ниже 8.
4. Оставшиеся отсортируй от высшего балла к низшему.
5. Оставь ТОЛЬКО 1 самую горячую новость с максимальной оценкой.

ВЕРНИ СТРОГО JSON (без markdown, без ```):
[
  {{
    "id": "ID новости",
    "score": 9,
    "headline": "Краткий заголовок на русском (до 80 символов)",
    "summary": "Суть в 1-2 предложениях на русском"
  }}
]

Если ни одна новость не набрала 8+, верни: []

НОВОСТИ ДЛЯ ОЦЕНКИ:
{news_text}
"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text) if text.startswith("[") else []
        filtered = sorted([r for r in result if r.get("score", 0) >= 8], key=lambda x: x.get("score", 0), reverse=True)
        return filtered[:1]  # только самая горячая новость
    except Exception as e:
        logger.error(f"Gemini digest error: {e}")
        return []


def gemini_post(title: str, description: str, link: str, has_photo: bool = False) -> str:
    photo_info = "ДА — фото будет приложено" if has_photo else "НЕТ — фото не будет, не упоминай визуал"
    prompt = POST_PROMPT.format(title=title, description=description, has_photo=photo_info)
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text.strip()

        if text.upper().startswith("SKIP"):
            return "SKIP"

        text = re.sub(r'Оригинал\s*\(?\s*https?://[^\s\)]+\)?\s*', '', text).strip()
        text = re.sub(r'https?://\S+', '', text).strip()

        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n\n'.join(lines)

        text += f'\n\n<a href="{CHANNEL_LINK}">Подписаться на KoreanMaks 🔥🚀🇰🇷</a>'
        return text
    except Exception as e:
        logger.error(f"Gemini post error: {e}")
        return f"❌ Ошибка генерации: {e}"


# ============================================================
# GEMINI CHAT (для внешнего приложения)
# ============================================================

CHAT_MODELS = {
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
}

def gemini_chat(message: str, history: list = None, model_name: str = "", system_prompt: str = "") -> str:
    """Простой чат с Gemini. history = [{"role":"user","text":"..."}, {"role":"model","text":"..."}]"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        use_model = model_name if model_name in CHAT_MODELS else GEMINI_MODEL
        model_kwargs = {}
        if system_prompt:
            model_kwargs["system_instruction"] = system_prompt
        model = genai.GenerativeModel(use_model, **model_kwargs)

        contents = []
        if history:
            for h in history:
                contents.append({"role": h["role"], "parts": [h["text"]]})
        contents.append({"role": "user", "parts": [message]})

        response = model.generate_content(contents)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini chat error: {e}")
        return f"❌ Ошибка: {e}"


# ============================================================
# ПРОВЕРКА ПОСЛЕДНЕГО ПОСТА В КАНАЛЕ
# ============================================================

def _seconds_since_last_channel_post() -> int:
    """Сколько секунд прошло с последней публикации в канал.
    Читает из SQLite (переживает рестарты/деплои).
    При самом первом запуске (БД пустая) — пробует узнать через Telegram API."""

    # Если уже постили когда-либо — значение есть в БД
    last_pub = _get_last_publish_time()
    if last_pub > 0:
        now = datetime.datetime.now().timestamp()
        return int(now - last_pub)

    interval = _get_interval()

    # Самый первый запуск (БД только что создана) — пробуем узнать через Telegram API
    try:
        result = tg_api("getChat", {"chat_id": CHANNEL_USERNAME})
        if result and result.get("ok"):
            chat = result.get("result", {})
            pinned = chat.get("pinned_message", {})
            if pinned and pinned.get("date"):
                now = datetime.datetime.now().timestamp()
                elapsed = int(now - pinned["date"])
                logger.info(f"📌 Pinned message age: {elapsed}s")
                # Закреплённое сообщение — не обязательно последнее,
                # но если оно свежее интервала — точно не надо постить
                if elapsed < interval:
                    return elapsed
    except Exception as e:
        logger.error(f"Check channel error: {e}")

    # Не удалось узнать — безопасно ждём ~30 минут после старта
    wait_after_start = max(interval - 1800, 600)
    _set_last_publish_time(datetime.datetime.now().timestamp() - (interval - wait_after_start))
    logger.info(f"⏰ First start — will post in ~{wait_after_start // 60} min")
    return interval - wait_after_start


# ============================================================
# АВТОПОСТИНГ — ЛУЧШАЯ НОВОСТЬ С ФОТО
# ============================================================

def send_news_digest(chat_id: str = None):
    """Находит лучшую новость (8+/10, с фото) и автоматически публикует в канал."""
    cid = chat_id or TELEGRAM_CHAT_ID
    logger.info("🚀 Auto best-news started")

    interval = _get_interval()

    # Проверяем: не слишком ли рано постить?
    if not chat_id:  # только для автопостинга, не для /news
        elapsed = _seconds_since_last_channel_post()
        if elapsed < interval:
            remaining = interval - elapsed
            logger.info(f"⏭ Слишком рано. Прошло {elapsed}с, интервал {interval}с. Ждём ещё {remaining}с")
            return

    config = FEEDS["korean"]

    logger.info("Fetching korean...")
    items = fetch_news(config["feeds"], "korean")
    if not items:
        logger.info("🤷 No news fetched")
        if chat_id:
            tg_send("🤷 Не удалось получить новости.", chat_id=cid)
        return

    # Слой 1: дедупликация по темам через Gemini (объединяем похожие новости)
    items = gemini_dedup_titles(items)

    digest_items = gemini_digest(items, config["topic_filter"])

    # Фильтруем: только не отправленные ранее (проверяем БД)
    candidates = [d for d in digest_items if not _is_sent(d.get("id", ""))]

    if not candidates:
        logger.info("🤷 No new quality news found")
        if chat_id:
            tg_send("🤷 Новых достойных новостей пока нет.", chat_id=cid)
        return

    # Сортируем по скору
    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Ищем лучшую НОВОСТЬ С ФОТО
    best = None
    news_item = None
    image_url = ""

    for candidate in candidates:
        nid = candidate["id"]
        ni = _state["news_cache"].get(nid)
        if not ni:
            continue
        img = _find_image_for(nid)
        if img:
            best = candidate
            news_item = ni
            image_url = img
            break
        else:
            logger.info(f"⏭ Пропуск (нет фото): {ni['title'][:50]}")

    if not best or not news_item:
        logger.info("🤷 No news with photo found")
        if chat_id:
            tg_send("🤷 Нет новостей с фото. Попробуй позже.", chat_id=cid)
        return

    nid = best["id"]

    # Генерируем пост
    post_text = gemini_post(news_item["title"], news_item["description"], news_item["link"], True)

    if post_text == "SKIP":
        logger.info(f"SKIP (clickbait): {news_item['title'][:50]}")
        # Пробуем следующего кандидата с фото
        for candidate in candidates:
            if candidate["id"] == nid:
                continue
            nid2 = candidate["id"]
            ni2 = _state["news_cache"].get(nid2)
            if not ni2:
                continue
            img2 = _find_image_for(nid2)
            if not img2:
                continue
            post_text2 = gemini_post(ni2["title"], ni2["description"], ni2["link"], True)
            if post_text2 != "SKIP":
                _auto_publish(nid2, post_text2, img2, candidate, cid)
                return
        if chat_id:
            tg_send("🤷 Все кандидаты оказались кликбейтом.", chat_id=cid)
        return

    _auto_publish(nid, post_text, image_url, best, cid)


def _auto_publish(nid: str, post_text: str, image_url: str, best: dict, chat_id: str):
    """Автоматически публикует в канал с фото."""
    score = best.get("score", "?")
    headline = best.get("headline", "")

    # Публикация в канал
    if len(post_text) <= 1024:
        result = tg_send_photo(image_url, post_text, chat_id=CHANNEL_USERNAME)
    else:
        tg_send_photo(image_url, f"🔥 {headline}", chat_id=CHANNEL_USERNAME)
        result = tg_api("sendMessage", {
            "chat_id": CHANNEL_USERNAME,
            "text": post_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })

    if result and result.get("ok"):
        _set_last_publish_time(datetime.datetime.now().timestamp())
        logger.info(f"✅ Auto-published: [{score}/10] {headline[:50]}")
        tg_send(f"🤖 <b>Автопост опубликован:</b>\n\n{headline}\n\n<i>(оценка: {score}/10)</i>", chat_id=chat_id)
        # Сохраняем в БД: и nid (защита от повторной отправки той же новости),
        # и headline/summary (чтобы Gemini не предлагал похожие темы)
        summary = best.get("summary", "")
        _save_published_topic(nid, headline, summary)
    else:
        logger.error(f"❌ Auto-publish failed: {headline[:50]}")
        tg_send(f"❌ Не удалось опубликовать. Бот — админ {CHANNEL_USERNAME}?", chat_id=chat_id)

    _state["last_post_text"] = post_text
    _state["last_post_nid"] = nid


# ============================================================
# ОБРАБОТКА КОМАНД
# ============================================================

def handle_update(update: dict):
    if "message" in update:
        msg = update["message"]
        text = (msg.get("text") or "").strip()
        chat_id = str(msg["chat"]["id"])

        if text == "/start": cmd_start(chat_id)
        elif text == "/news":
            tg_send("⏳ Ищу лучшую новость...", chat_id=chat_id)
            send_news_digest(chat_id)
        elif text == "/interval": cmd_interval(chat_id)
        elif text == "/help": cmd_help(chat_id)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        data = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])

        if data.startswith("int:"):
            h = float(data.split(":", 1)[1])
            _set_interval(int(h * 3600))
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"Интервал: {_interval_text(int(h*3600))}"})
            cmd_interval_update(chat_id, cb["message"]["message_id"])
        else:
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id})


# ============================================================
# КОМАНДЫ
# ============================================================

def cmd_start(chat_id: str):
    tg_send(f"👋 <b>Новостной бот — Корейский шоубиз</b>\n\n"
            f"<b>Интервал:</b> {_interval_text(_get_interval())}\n"
            f"<b>Режим:</b> автопост лучшей новости с фото (8+/10)\n"
            f"<b>Канал:</b> {CHANNEL_USERNAME}\n\n"
            "<b>Команды:</b>\n/news — лучшая новость сейчас\n"
            "/interval — частота\n/help — справка", chat_id=chat_id)

def cmd_help(chat_id: str):
    tg_send("📖 <b>Как работает:</b>\n\n"
            f"Каждые {_interval_text(_get_interval())} бот:\n"
            "1️⃣ Парсит RSS-ленты корейского шоубиза\n"
            "2️⃣ Gemini оценивает новости (8+/10)\n"
            "3️⃣ Лучшая новость С ФОТО публикуется в канал\n"
            "4️⃣ Тебе приходит уведомление\n\n"
            "/news — запросить сейчас\n"
            "/interval — изменить частоту", chat_id=chat_id)

def cmd_interval(chat_id: str):
    interval = _get_interval()
    cur = interval / 3600
    b, r = [], []
    for h in [2, 4, 6, 8, 12]:
        label = f"{h}ч"
        sel = '✅ ' if abs(h - cur) < 0.01 else ''
        r.append({"text": f"{sel}{label}", "callback_data": f"int:{h}"})
        if len(r) == 3: b.append(r); r = []
    if r: b.append(r)
    tg_send(f"⏰ Сейчас: каждые <b>{_interval_text(interval)}</b>", reply_markup={"inline_keyboard": b}, chat_id=chat_id)

def cmd_interval_update(chat_id: str, mid: int):
    interval = _get_interval()
    cur = interval / 3600
    b, r = [], []
    for h in [2, 4, 6, 8, 12]:
        label = f"{h}ч"
        sel = '✅ ' if abs(h - cur) < 0.01 else ''
        r.append({"text": f"{sel}{label}", "callback_data": f"int:{h}"})
        if len(r) == 3: b.append(r); r = []
    if r: b.append(r)
    tg_api("editMessageText", {"chat_id": chat_id, "message_id": mid,
        "text": f"⏰ Сейчас: каждые <b>{_interval_text(interval)}</b>",
        "parse_mode": "HTML", "reply_markup": {"inline_keyboard": b}})


# ============================================================
# ПОТОКИ (2 вместо 3)
# ============================================================

def polling_loop():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    logger.info("🎧 Polling started")
    while True:
        try:
            resp = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            if resp.status_code != 200:
                logger.error(f"Polling error {resp.status_code}"); time.sleep(5); continue
            for u in resp.json().get("result", []):
                offset = u["update_id"] + 1
                try: handle_update(u)
                except Exception as e: logger.error(f"Update error: {e}")
        except requests.exceptions.Timeout: continue
        except Exception as e: logger.error(f"Polling error: {e}"); time.sleep(5)

def scheduler_loop():
    logger.info("⏰ Scheduler started")
    # Не постим сразу при старте — проверяем интервал с последнего поста
    while True:
        time.sleep(60)  # проверяем каждую минуту
        elapsed = _seconds_since_last_channel_post()
        if elapsed >= _get_interval():
            try:
                send_news_digest()
            except Exception as e:
                logger.error(f"Scheduled digest error: {e}")
            # После попытки поста — спим минимум 10 минут чтобы не долбить
            time.sleep(600)

def start():
    if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logger.warning("⚠ Bot env vars not set — bot disabled"); return
    # Инициализация БД и одноразовая миграция старого JSON
    _init_db()
    _migrate_json_to_db()
    threading.Thread(target=polling_loop, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    logger.info("🤖 News bot started (2 threads: polling, digest)")

start()
