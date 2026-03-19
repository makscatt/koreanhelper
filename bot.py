#!/usr/bin/env python3
"""
Gemini News Bot — Корейский шоубиз + Мировое кино
Работает ВНУТРИ Flask-приложения на Render.
Ключи читает из переменных окружения (Environment Variables на Render).

Подключение: в app.py добавить одну строку:
    import bot
"""

import os
import re
import json
import hashlib
import logging
import datetime
import threading
import time

import feedparser
import requests
import google.generativeai as genai

# ============================================================
# НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (Render Environment)
# ============================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Модель Gemini
GEMINI_MODEL = "gemini-1.5-flash"

# Интервал отправки сводки (в секундах). 4 часа = 14400
NEWS_INTERVAL = 4 * 60 * 60

# Сколько новостей брать с каждого источника
NEWS_PER_FEED = 10

# Максимальная длина сообщения Telegram
TG_MAX_LENGTH = 4000

# ============================================================
# RSS-ИСТОЧНИКИ
# ============================================================

KOREAN_FEEDS = [
    "https://www.soompi.com/feed",
    "https://www.koreaboo.com/feed",
    "https://www.kpopstarz.com/rss/archives/all.xml",
    "https://www.koreaherald.com/rss/kpop",
    "https://www.allkpop.com/rss",
]

CINEMA_FEEDS = [
    "https://variety.com/feed",
    "https://deadline.com/feed",
    "https://www.hollywoodreporter.com/c/movies/feed",
    "https://feeds.feedburner.com/slashfilm",
]

# ============================================================
# ТЕМАТИКА
# ============================================================

TOPIC_KOREAN = (
    "Корейская индустрия развлечений: K-pop (новые релизы, скандалы, камбэки, "
    "концерты, рекорды), K-drama (новые дорамы, кастинги, рейтинги), "
    "корейские фильмы, награды, корейские знаменитости."
)

TOPIC_CINEMA = (
    "Мировая киноиндустрия: самые резонансные новости — Оскар, Канны и другие "
    "кинопремии, громкие премьеры, бокс-офис рекорды, скандалы в Голливуде, "
    "кастинги в крупных проектах, стриминговые войны."
)

# ============================================================
# ПРОМПТ ДЛЯ ГЕНЕРАЦИИ ПОСТА
# ============================================================

POST_PROMPT = """
Ты — блогер, который ведёт популярный Telegram-канал о корейской культуре и кино.
Твой стиль: разговорный, живой, с эмоциями, как будто рассказываешь другу.

Напиши пост для Telegram-канала на основе этой новости:

Заголовок: {title}
Описание: {description}
Ссылка: {link}

ПРАВИЛА:
1. Пиши на русском языке.
2. Длина: 800-1500 символов.
3. Начни с цепляющего хука — вопрос, восклицание или провокация.
4. Изложи суть своими словами, добавь свои мысли/реакцию.
5. Используй эмодзи уместно (3-5 штук).
6. Заверши призывом к обсуждению.
7. Добавь 3-5 хештегов в конце.
8. Ссылку на оригинал вставь перед хештегами.
9. НЕ используй HTML-теги, пиши чистым текстом.
10. Тон: дружелюбный, увлечённый, немного дерзкий.
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
# КЭШ НОВОСТЕЙ (в памяти, для кнопок)
# ============================================================

_news_cache: dict = {}


def _news_id(title: str, link: str) -> str:
    raw = f"{title}|{link}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ============================================================
# TELEGRAM API (прямые HTTP-запросы, без библиотек)
# ============================================================

def tg_send(text: str, reply_markup: dict = None):
    """Отправка сообщения в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Разбиваем длинные сообщения
    chunks = []
    if len(text) <= TG_MAX_LENGTH:
        chunks = [text]
    else:
        parts = text.split("\n\n")
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 > TG_MAX_LENGTH:
                if current:
                    chunks.append(current.strip())
                current = part
            else:
                current += "\n\n" + part if current else part
        if current:
            chunks.append(current.strip())

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        # Кнопки только к последнему чанку
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            resp = requests.post(url, data=payload, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Telegram {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

        if i < len(chunks) - 1:
            time.sleep(1)


def tg_send_with_button(text: str, news_id: str):
    """Отправка новости с кнопкой «Напиши пост»."""
    markup = {
        "inline_keyboard": [[
            {"text": "📝 Напиши пост", "callback_data": f"post:{news_id}"}
        ]]
    }
    tg_send(text, reply_markup=markup)


def tg_answer_callback(callback_id: str, text: str = ""):
    """Ответ на нажатие кнопки."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, data={
            "callback_query_id": callback_id,
            "text": text,
        }, timeout=10)
    except Exception:
        pass


def tg_send_reply(chat_id: str, text: str, reply_markup: dict = None):
    """Отправка ответа в конкретный чат."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, data=payload, timeout=30)
    except Exception as e:
        logger.error(f"Telegram reply error: {e}")


# ============================================================
# ПАРСИНГ RSS
# ============================================================

def fetch_news(feeds: list, section: str) -> list:
    items = []

    for url in feeds:
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                logger.warning(f"Parse failed: {url}")
                continue

            source = feed.feed.get("title", url)

            for entry in feed.entries[:NEWS_PER_FEED]:
                title = entry.get("title", "").strip()
                desc = entry.get("description", "").strip()
                link = entry.get("link", "").strip()

                desc = re.sub(r"<[^>]+>", "", desc)
                if len(desc) > 500:
                    desc = desc[:500] + "..."

                nid = _news_id(title, link)

                item = {
                    "id": nid,
                    "title": title,
                    "description": desc,
                    "link": link,
                    "source": source,
                    "section": section,
                }

                _news_cache[nid] = item
                items.append(item)

        except Exception as e:
            logger.error(f"RSS error {url}: {e}")
            continue

    logger.info(f"[{section}] Fetched: {len(items)}")
    return items


# ============================================================
# GEMINI
# ============================================================

def gemini_digest(news_items: list, topic: str) -> list:
    """Фильтрует новости через Gemini, возвращает JSON-список."""
    news_text = ""
    for item in news_items:
        news_text += (
            f"[ID: {item['id']}]\n"
            f"Источник: {item['source']}\n"
            f"Заголовок: {item['title']}\n"
            f"Описание: {item['description']}\n"
            f"Ссылка: {item['link']}\n\n"
        )

    prompt = f"""
Ты — профессиональный редактор новостного Telegram-канала на русском языке.

Проанализируй новости и выбери 3-7 самых интересных/резонансных по теме:
«{topic}»

ВЕРНИ ОТВЕТ СТРОГО В JSON (без markdown, без ```):
[
  {{
    "id": "ID новости",
    "headline": "Краткий заголовок на русском (до 80 символов)",
    "summary": "Суть в 1-2 предложениях на русском"
  }}
]

Если подходящих новостей нет, верни: []

НОВОСТИ:
{news_text}
"""

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except Exception as e:
        logger.error(f"Gemini digest error: {e}")
        return []


def gemini_post(title: str, description: str, link: str) -> str:
    """Генерирует пост для Telegram-канала."""
    prompt = POST_PROMPT.format(title=title, description=description, link=link)

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini post error: {e}")
        return f"❌ Ошибка генерации: {e}"


# ============================================================
# СВОДКА НОВОСТЕЙ
# ============================================================

def send_news_digest():
    """Собирает новости, фильтрует, отправляет с кнопками."""
    logger.info("=" * 40)
    logger.info("🚀 News digest started")

    today = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    tg_send(f"📰 <b>Новостная сводка</b>  •  {today}\n{'—' * 30}")

    # --- Корейский шоубиз ---
    logger.info("Fetching Korean entertainment...")
    korean_items = fetch_news(KOREAN_FEEDS, "korean")
    if korean_items:
        digest = gemini_digest(korean_items, TOPIC_KOREAN)
        if digest:
            tg_send("🇰🇷 <b>КОРЕЙСКИЙ ШОУБИЗ</b>")
            for item in digest:
                nid = item.get("id", "")
                headline = item.get("headline", "—")
                summary = item.get("summary", "")
                text = f"<b>🔹 {headline}</b>\n{summary}"
                tg_send_with_button(text, nid)
                time.sleep(0.5)

    time.sleep(2)

    # --- Мировое кино ---
    logger.info("Fetching cinema news...")
    cinema_items = fetch_news(CINEMA_FEEDS, "cinema")
    if cinema_items:
        digest = gemini_digest(cinema_items, TOPIC_CINEMA)
        if digest:
            tg_send("\n🎬 <b>МИРОВОЕ КИНО</b>")
            for item in digest:
                nid = item.get("id", "")
                headline = item.get("headline", "—")
                summary = item.get("summary", "")
                text = f"<b>🔹 {headline}</b>\n{summary}"
                tg_send_with_button(text, nid)
                time.sleep(0.5)

    logger.info("✅ Digest sent!")


# ============================================================
# ОБРАБОТКА НАЖАТИЙ КНОПОК (polling в фоне)
# ============================================================

def handle_update(update: dict):
    """Обрабатывает одно обновление от Telegram."""

    # --- Команды ---
    if "message" in update:
        msg = update["message"]
        text = msg.get("text", "")
        chat_id = str(msg["chat"]["id"])

        if text == "/start":
            tg_send_reply(chat_id, (
                "👋 <b>Привет! Я новостной бот.</b>\n\n"
                "Каждые 4 часа присылаю сводку новостей о корейском шоубизе "
                "и мировом кино.\n\n"
                "По каждой новости — кнопка <b>«📝 Напиши пост»</b>, "
                "и я сгенерирую готовый пост для канала.\n\n"
                "/news — сводка прямо сейчас"
            ))

        elif text == "/news":
            tg_send_reply(chat_id, "⏳ Собираю новости, 20-30 секунд...")
            send_news_digest()

    # --- Кнопки ---
    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        data = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])

        if data.startswith("post:"):
            tg_answer_callback(cb_id, "⏳ Генерирую пост...")

            nid = data.split(":", 1)[1]
            news_item = _news_cache.get(nid)

            if not news_item:
                tg_send_reply(chat_id, "❌ Новость не найдена. Запросите /news заново.")
                return

            logger.info(f"Generating post: {news_item['title'][:50]}...")

            post_text = gemini_post(
                news_item["title"],
                news_item["description"],
                news_item["link"],
            )

            # Кнопка «переписать»
            markup = {
                "inline_keyboard": [[
                    {"text": "🔄 Переписать", "callback_data": f"post:{nid}"}
                ]]
            }

            tg_send_reply(chat_id, f"✅ <b>Готовый пост:</b>\n\n{post_text}", markup)

        else:
            tg_answer_callback(cb_id)


def polling_loop():
    """Фоновый поток: слушает обновления от Telegram (long polling)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0

    logger.info("🎧 Polling started")

    while True:
        try:
            resp = requests.get(url, params={
                "offset": offset,
                "timeout": 30,
            }, timeout=35)

            if resp.status_code != 200:
                logger.error(f"Polling error {resp.status_code}")
                time.sleep(5)
                continue

            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception as e:
                    logger.error(f"Update handling error: {e}")

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


def scheduler_loop():
    """Фоновый поток: отправляет сводку по расписанию."""
    logger.info(f"⏰ Scheduler started (every {NEWS_INTERVAL // 3600}h)")

    # Первая сводка через 30 секунд после старта
    time.sleep(30)
    send_news_digest()

    while True:
        time.sleep(NEWS_INTERVAL)
        try:
            send_news_digest()
        except Exception as e:
            logger.error(f"Scheduled digest error: {e}")


# ============================================================
# ЗАПУСК (вызывается при import bot в app.py)
# ============================================================

def start():
    """Запускает бота в фоновых потоках."""
    if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logger.warning("⚠ Bot env vars not set — bot disabled")
        return

    # Поток 1: слушает кнопки
    t1 = threading.Thread(target=polling_loop, daemon=True)
    t1.start()

    # Поток 2: шлёт сводки по расписанию
    t2 = threading.Thread(target=scheduler_loop, daemon=True)
    t2.start()

    logger.info("🤖 News bot started (2 background threads)")


# Автозапуск при импорте
start()
