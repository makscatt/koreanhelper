#!/usr/bin/env python3
"""
Gemini News Bot — Корейский шоубиз + Мировое кино
Работает ВНУТРИ Flask-приложения на Render.
Ключи читает из переменных окружения (Environment Variables на Render).

Подключение: в app.py добавить одну строку:
    import bot

Команды бота:
    /start    — приветствие и список команд
    /news     — получить сводку прямо сейчас
    /topics   — включить/выключить тематики
    /interval — изменить частоту сводок
    /help     — справк
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

GEMINI_MODEL = "gemini-3.1-pro-preview"
NEWS_PER_FEED = 10
TG_MAX_LENGTH = 4000

# ============================================================
# СОСТОЯНИЕ БОТА (в памяти, сбрасывается при рестарте)
# ============================================================

_state = {
    "interval": 4 * 60 * 60,       # интервал в секундах (по умолчанию 4ч)
    "topics": {
        "korean": True,             # корейский шоубиз включён
        "cinema": True,             # мировое кино включено
    },
    "news_cache": {},               # кэш новостей для кнопок
}

# ============================================================
# RSS-ИСТОЧНИКИ
# ============================================================

FEEDS = {
    "korean": {
        "label": "🇰🇷 Корейский шоубиз",
        "feeds": [
            "https://www.soompi.com/feed",
            "https://www.koreaboo.com/feed",
            "https://www.kpopstarz.com/rss/archives/all.xml",
            "https://www.koreaherald.com/rss/kpop",
            "https://www.allkpop.com/rss",
        ],
        "topic": (
            "Корейская индустрия развлечений: K-pop (новые релизы, скандалы, камбэки, "
            "концерты, рекорды), K-drama (новые дорамы, кастинги, рейтинги), "
            "корейские фильмы, награды, корейские знаменитости."
        ),
    },
    "cinema": {
        "label": "🎬 Мировое кино",
        "feeds": [
            "https://variety.com/feed",
            "https://deadline.com/feed",
            "https://www.hollywoodreporter.com/c/movies/feed",
            "https://feeds.feedburner.com/slashfilm",
        ],
        "topic": (
            "Мировая киноиндустрия: самые резонансные новости — Оскар, Канны и другие "
            "кинопремии, громкие премьеры, бокс-офис рекорды, скандалы в Голливуде, "
            "кастинги в крупных проектах, стриминговые войны."
        ),
    },
}

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
# TELEGRAM API
# ============================================================

def tg_api(method: str, payload: dict):
    """Вызов любого метода Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            logger.error(f"TG {method} {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"TG {method} error: {e}")
        return None


def tg_send(text: str, reply_markup: dict = None, chat_id: str = None):
    """Отправка сообщения. Разбивает длинные."""
    cid = chat_id or TELEGRAM_CHAT_ID

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
            "chat_id": cid,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        tg_api("sendMessage", payload)
        if i < len(chunks) - 1:
            time.sleep(0.5)


def tg_send_with_button(text: str, news_id: str, chat_id: str = None):
    """Новость с кнопкой «Напиши пост»."""
    markup = {
        "inline_keyboard": [[
            {"text": "📝 Напиши пост", "callback_data": f"post:{news_id}"}
        ]]
    }
    tg_send(text, reply_markup=markup, chat_id=chat_id)


# ============================================================
# УТИЛИТЫ
# ============================================================

def _news_id(title: str, link: str) -> str:
    raw = f"{title}|{link}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _interval_text(seconds: int) -> str:
    hours = seconds // 3600
    if hours == 1:
        return "1 час"
    elif hours < 5:
        return f"{hours} часа"
    else:
        return f"{hours} часов"


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
                    "id": nid, "title": title, "description": desc,
                    "link": link, "source": source, "section": section,
                }
                _state["news_cache"][nid] = item
                items.append(item)
        except Exception as e:
            logger.error(f"RSS error {url}: {e}")
    logger.info(f"[{section}] Fetched: {len(items)}")
    return items


# ============================================================
# GEMINI
# ============================================================

def gemini_digest(news_items: list, topic: str) -> list:
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

def send_news_digest(chat_id: str = None):
    cid = chat_id or TELEGRAM_CHAT_ID
    logger.info("🚀 News digest started")

    today = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    tg_send(f"📰 <b>Новостная сводка</b>  •  {today}\n{'—' * 30}", chat_id=cid)

    active_topics = {k: v for k, v in FEEDS.items() if _state["topics"].get(k, True)}

    if not active_topics:
        tg_send("⚠ Все тематики выключены. Используйте /topics чтобы включить.", chat_id=cid)
        return

    for key, config in active_topics.items():
        logger.info(f"Fetching {key}...")
        items = fetch_news(config["feeds"], key)
        if items:
            digest = gemini_digest(items, config["topic"])
            if digest:
                tg_send(f"\n{config['label'].upper()}\n", chat_id=cid)
                for item in digest:
                    nid = item.get("id", "")
                    headline = item.get("headline", "—")
                    summary = item.get("summary", "")
                    text = f"<b>🔹 {headline}</b>\n{summary}"
                    tg_send_with_button(text, nid, chat_id=cid)
                    time.sleep(0.5)
        time.sleep(2)

    logger.info("✅ Digest sent!")


# ============================================================
# ОБРАБОТКА КОМАНД И КНОПОК
# ============================================================

def handle_update(update: dict):
    """Обрабатывает одно обновление от Telegram."""

    # --- Текстовые команды ---
    if "message" in update:
        msg = update["message"]
        text = (msg.get("text") or "").strip()
        chat_id = str(msg["chat"]["id"])

        if text == "/start":
            cmd_start(chat_id)
        elif text == "/news":
            tg_send("⏳ Собираю новости, 20-30 секунд...", chat_id=chat_id)
            send_news_digest(chat_id)
        elif text == "/topics":
            cmd_topics(chat_id)
        elif text == "/interval":
            cmd_interval(chat_id)
        elif text == "/help":
            cmd_help(chat_id)

    # --- Нажатия кнопок ---
    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        data = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])

        # --- Напиши пост ---
        if data.startswith("post:"):
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "⏳ Генерирую пост..."})
            nid = data.split(":", 1)[1]
            news_item = _state["news_cache"].get(nid)

            if not news_item:
                tg_send("❌ Новость не найдена. Запросите /news заново.", chat_id=chat_id)
                return

            logger.info(f"Generating post: {news_item['title'][:50]}...")
            post_text = gemini_post(news_item["title"], news_item["description"], news_item["link"])

            markup = {"inline_keyboard": [[
                {"text": "🔄 Переписать", "callback_data": f"post:{nid}"}
            ]]}
            tg_send(f"✅ <b>Готовый пост:</b>\n\n{post_text}", reply_markup=markup, chat_id=chat_id)

        # --- Переключение тематики ---
        elif data.startswith("topic:"):
            key = data.split(":", 1)[1]
            if key in _state["topics"]:
                _state["topics"][key] = not _state["topics"][key]
                status = "✅ вкл" if _state["topics"][key] else "❌ выкл"
                label = FEEDS[key]["label"]
                tg_api("answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": f"{label} — {status}",
                })
                # Обновляем сообщение с кнопками
                cmd_topics_update(chat_id, cb["message"]["message_id"])

        # --- Смена интервала ---
        elif data.startswith("int:"):
            hours = int(data.split(":", 1)[1])
            _state["interval"] = hours * 3600
            tg_api("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": f"Интервал: {_interval_text(hours * 3600)}",
            })
            cmd_interval_update(chat_id, cb["message"]["message_id"])

        else:
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id})


# ============================================================
# КОМАНДЫ
# ============================================================

def cmd_start(chat_id: str):
    topics_status = ""
    for key, config in FEEDS.items():
        status = "✅" if _state["topics"].get(key, True) else "❌"
        topics_status += f"  {status} {config['label']}\n"

    text = (
        "👋 <b>Привет! Я ваш новостной бот.</b>\n\n"
        "Собираю новости, фильтрую через Gemini AI "
        "и присылаю сводку в Telegram.\n\n"
        f"<b>Активные тематики:</b>\n{topics_status}\n"
        f"<b>Интервал:</b> каждые {_interval_text(_state['interval'])}\n\n"
        "<b>Команды:</b>\n"
        "/news — сводка прямо сейчас\n"
        "/topics — включить/выключить тематики\n"
        "/interval — изменить частоту сводок\n"
        "/help — справка\n\n"
        "Под каждой новостью — кнопка <b>«📝 Напиши пост»</b>, "
        "я сгенерирую готовый текст для канала!"
    )
    tg_send(text, chat_id=chat_id)


def cmd_help(chat_id: str):
    text = (
        "📖 <b>Как пользоваться:</b>\n\n"
        "1️⃣ Каждые N часов присылаю сводку новостей.\n"
        "2️⃣ Под каждой новостью — кнопка <b>«📝 Напиши пост»</b>.\n"
        "3️⃣ Нажмите — получите готовый пост в блогерском стиле.\n"
        "4️⃣ Не понравился? <b>«🔄 Переписать»</b> — новый вариант.\n"
        "5️⃣ Перешлите пост в свой канал!\n\n"
        "<b>Настройки:</b>\n"
        "/topics — выбрать какие тематики отслеживать\n"
        "/interval — как часто получать сводки\n"
        "/news — не ждать, получить сводку сейчас"
    )
    tg_send(text, chat_id=chat_id)


def cmd_topics(chat_id: str):
    """Показывает тематики с кнопками вкл/выкл."""
    buttons = []
    for key, config in FEEDS.items():
        status = "✅" if _state["topics"].get(key, True) else "❌"
        buttons.append([{
            "text": f"{status} {config['label']}",
            "callback_data": f"topic:{key}",
        }])

    markup = {"inline_keyboard": buttons}
    tg_send(
        "⚙️ <b>Тематики</b>\n\nНажмите чтобы включить/выключить:",
        reply_markup=markup,
        chat_id=chat_id,
    )


def cmd_topics_update(chat_id: str, message_id: int):
    """Обновляет сообщение с тематиками после нажатия."""
    buttons = []
    for key, config in FEEDS.items():
        status = "✅" if _state["topics"].get(key, True) else "❌"
        buttons.append([{
            "text": f"{status} {config['label']}",
            "callback_data": f"topic:{key}",
        }])

    tg_api("editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": "⚙️ <b>Тематики</b>\n\nНажмите чтобы включить/выключить:",
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons},
    })


def cmd_interval(chat_id: str):
    """Показывает выбор интервала."""
    current = _state["interval"] // 3600
    options = [1, 2, 4, 6, 8, 12]

    buttons = []
    row = []
    for h in options:
        label = f"{'✅ ' if h == current else ''}{h}ч"
        row.append({"text": label, "callback_data": f"int:{h}"})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    markup = {"inline_keyboard": buttons}
    tg_send(
        f"⏰ <b>Частота сводок</b>\n\nСейчас: каждые <b>{_interval_text(_state['interval'])}</b>\nВыберите новый интервал:",
        reply_markup=markup,
        chat_id=chat_id,
    )


def cmd_interval_update(chat_id: str, message_id: int):
    """Обновляет сообщение с интервалом после нажатия."""
    current = _state["interval"] // 3600
    options = [1, 2, 4, 6, 8, 12]

    buttons = []
    row = []
    for h in options:
        label = f"{'✅ ' if h == current else ''}{h}ч"
        row.append({"text": label, "callback_data": f"int:{h}"})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    tg_api("editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": f"⏰ <b>Частота сводок</b>\n\nСейчас: каждые <b>{_interval_text(_state['interval'])}</b>\nВыберите новый интервал:",
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons},
    })


# ============================================================
# ФОНОВЫЕ ПОТОКИ
# ============================================================

def polling_loop():
    """Слушает обновления от Telegram (long polling)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    logger.info("🎧 Polling started")

    while True:
        try:
            resp = requests.get(url, params={
                "offset": offset, "timeout": 30,
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
                    logger.error(f"Update error: {e}")

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


def scheduler_loop():
    """Отправляет сводку по расписанию."""
    logger.info("⏰ Scheduler started")

    # Первая сводка через 30 секунд после старта
    time.sleep(30)
    try:
        send_news_digest()
    except Exception as e:
        logger.error(f"First digest error: {e}")

    while True:
        time.sleep(_state["interval"])
        try:
            send_news_digest()
        except Exception as e:
            logger.error(f"Scheduled digest error: {e}")


# ============================================================
# ЗАПУСК
# ============================================================

def start():
    """Запускает бота в фоновых потоках."""
    if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logger.warning("⚠ Bot env vars not set — bot disabled")
        return

    t1 = threading.Thread(target=polling_loop, daemon=True)
    t1.start()

    t2 = threading.Thread(target=scheduler_loop, daemon=True)
    t2.start()

    logger.info("🤖 News bot started (2 background threads)")


# Автозапуск при импорте
start()
