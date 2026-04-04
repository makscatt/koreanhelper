#!/usr/bin/env python3
"""
Gemini News Bot — Корейский шоубиз
Автопостинг лучших новостей (8+/10) с фото в @KoreanMaks каждые 4 часа.
Работает ВНУТРИ Flask-приложения на Render.

Логика: бот проверяет время последнего поста в канале TG,
отсчитывает от него интервал (по умолчанию 4 часа),
и только когда время пришло — парсит RSS и публикует.

Подключение: в app.py добавить:  import bot
"""

import os
import re
import json
import hashlib
import logging
import threading
import time
from datetime import datetime, timezone

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
GEMINI_MODEL = "gemini-2.5-flash"
NEWS_PER_FEED = 10
TG_MAX_LENGTH = 4000
CHECK_INTERVAL = 60  # проверяем каждые 60 секунд, пора ли постить

# ============================================================
# СОСТОЯНИЕ
# ============================================================

_state = {
    "interval": int(4 * 60 * 60),   # 4 часа
    "last_post_text": "",
    "last_post_nid": "",
    "sent_news_ids": set(),
}

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
# ПОЛУЧЕНИЕ ВРЕМЕНИ ПОСЛЕДНЕГО ПОСТА В КАНАЛЕ
# ============================================================

def get_last_channel_post_time() -> float | None:
    """
    Получает время последнего поста в канале через Telegram Bot API.
    Возвращает Unix timestamp или None если не удалось получить.
    """
    # Способ 1: getChat — у каналов есть поле message с последним постом
    # Но оно не всегда доступно. Используем forwardMessage-подход не подходит.
    # Лучший способ: getUpdates по channel_post или getChatMemberCount не даёт время.
    #
    # Самый надёжный: отправить невидимое сообщение и удалить — слишком грязно.
    # Реальный рабочий способ: использовать getChat, у каждого канала
    # Bot API не даёт прямо "последний пост". Но мы можем использовать
    # channel_post из getUpdates, либо хранить время нашего последнего поста.
    #
    # Используем комбинацию:
    # 1. Пробуем получить channel_post из getUpdates (если бот — админ канала)
    # 2. Если нет — берём сохранённое время последней публикации

    # Попробуем через getUpdates с allowed_updates=["channel_post"]
    # Но это конфликтует с polling. Поэтому используем отдельный подход:
    # Храним _state["last_publish_ts"] и обновляем при каждой публикации.
    # А при первом запуске — пробуем получить через getChat.

    # Если у нас уже есть сохранённое время — возвращаем его
    if _state.get("last_publish_ts"):
        return _state["last_publish_ts"]

    # При первом запуске пытаемся узнать время через getChatHistory
    # К сожалению Bot API не даёт getChatHistory.
    # Используем workaround: отправляем getChat и проверяем pinned_message
    result = tg_api("getChat", {"chat_id": CHANNEL_USERNAME})
    if result and result.get("ok"):
        chat_data = result.get("result", {})
        # Если есть закреплённое сообщение — берём его дату как ориентир
        pinned = chat_data.get("pinned_message")
        if pinned and pinned.get("date"):
            logger.info(f"📌 Found pinned message date: {pinned['date']}")
            return float(pinned["date"])

    # Если ничего не нашли — возвращаем None (нужно постить сразу)
    return None


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


def _find_image(news_items: list, nid: str) -> str:
    """Ищет фото для новости по списку спарсенных элементов."""
    # Сначала ищем в самой новости
    for item in news_items:
        if item["id"] == nid and item.get("image"):
            return item["image"]

    # Потом ищем по похожим заголовкам
    target_title = ""
    for item in news_items:
        if item["id"] == nid:
            target_title = item.get("title", "").lower()
            break
    if not target_title:
        return ""

    keywords = [w for w in re.split(r'\W+', target_title) if len(w) > 4]
    if not keywords:
        return ""

    best_match = ""
    best_score = 0
    for item in news_items:
        if item["id"] == nid or not item.get("image"):
            continue
        other_title = item.get("title", "").lower()
        score = sum(1 for kw in keywords if kw in other_title)
        if score > best_score and score >= 2:
            best_score = score
            best_match = item["image"]

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
# ПАРСИНГ RSS
# ============================================================

def fetch_news(feeds: list, section: str) -> list:
    """Парсит RSS-ленты и возвращает список новостей. Не кеширует."""
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

    prompt = f"""
Ты — строгий редактор новостного канала. Твоя задача — отобрать ТОЛЬКО по-настоящему важные и резонансные новости.

ТЕМАТИКА И КРИТЕРИИ ОЦЕНКИ:
{topic_filter}

ЖЁСТКОЕ ПРАВИЛО ДЕДУПЛИКАЦИИ:
Если несколько новостей описывают ОДНО И ТО ЖЕ событие (даже если из разных источников, разными словами, с разных углов) — это ДУБЛИ.
Оставляй ТОЛЬКО ОДНУ — ту, где больше конкретики и деталей. Остальные дубли ВЫКИДЫВАЙ полностью.

ИНСТРУКЦИЯ:
1. Сначала найди и удали все дубли (оставь только лучший вариант каждого события).
2. Оцени КАЖДУЮ оставшуюся новость по шкале 1-10.
3. ВЫКИНЬ всё что ниже 8.
4. Оставшиеся отсортируй от высшего балла к низшему.
5. Оставь максимум 5 новостей.

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
        return [r for r in result if r.get("score", 0) >= 8]
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

def gemini_chat(message: str, history: list = None) -> str:
    """Простой чат с Gemini. history = [{"role":"user","text":"..."}, {"role":"model","text":"..."}]"""
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)

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
# АВТОПОСТИНГ — ЛУЧШАЯ НОВОСТЬ С ФОТО
# ============================================================

def send_news_digest(chat_id: str = None):
    """
    Парсит RSS, находит лучшую новость (8+/10, с фото)
    и автоматически публикует в канал.
    Без кеша — всё парсится в момент вызова.
    """
    cid = chat_id or TELEGRAM_CHAT_ID
    logger.info("🚀 Auto best-news started")

    config = FEEDS["korean"]

    # Парсим RSS прямо сейчас (без кеша)
    logger.info("Fetching korean...")
    items = fetch_news(config["feeds"], "korean")
    if not items:
        logger.info("🤷 No news fetched")
        if chat_id:
            tg_send("🤷 Не удалось получить новости.", chat_id=cid)
        return

    # Фильтруем через Gemini
    digest_items = gemini_digest(items, config["topic_filter"])

    # Фильтруем: только не отправленные ранее
    candidates = [d for d in digest_items if d.get("id") not in _state["sent_news_ids"]]

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
        # Ищем новость в свежеспарсенном списке
        ni = next((it for it in items if it["id"] == nid), None)
        if not ni:
            continue
        img = _find_image(items, nid)
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
    _state["sent_news_ids"].add(nid)

    # Генерируем пост
    post_text = gemini_post(news_item["title"], news_item["description"], news_item["link"], True)

    if post_text == "SKIP":
        logger.info(f"SKIP (clickbait): {news_item['title'][:50]}")
        # Пробуем следующего кандидата с фото
        for candidate in candidates:
            if candidate["id"] == nid:
                continue
            nid2 = candidate["id"]
            ni2 = next((it for it in items if it["id"] == nid2), None)
            if not ni2:
                continue
            img2 = _find_image(items, nid2)
            if not img2:
                continue
            _state["sent_news_ids"].add(nid2)
            post_text2 = gemini_post(ni2["title"], ni2["description"], ni2["link"], True)
            if post_text2 != "SKIP":
                _auto_publish(nid2, post_text2, img2, candidate, cid)
                return
        if chat_id:
            tg_send("🤷 Все кандидаты оказались кликбейтом.", chat_id=cid)
        return

    _auto_publish(nid, post_text, image_url, best, cid)


def _auto_publish(nid: str, post_text: str, image_url: str, best: dict, chat_id: str):
    """Автоматически публикует в канал с фото и обновляет время последнего поста."""
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
        # Обновляем время последней публикации
        _state["last_publish_ts"] = time.time()
        logger.info(f"✅ Auto-published: [{score}/10] {headline[:50]}")
        tg_send(f"🤖 <b>Автопост опубликован:</b>\n\n{headline}\n\n<i>(оценка: {score}/10)</i>", chat_id=chat_id)
    else:
        logger.error(f"❌ Auto-publish failed: {headline[:50]}")
        tg_send(f"❌ Не удалось опубликовать. Бот — админ {CHANNEL_USERNAME}?", chat_id=chat_id)

    _state["last_post_text"] = post_text
    _state["last_post_nid"] = nid


# ============================================================
# ОБРАБОТКА КОМАНД
# ============================================================

def handle_update(update: dict):
    # Отслеживаем посты в канале для определения времени последнего поста
    if "channel_post" in update:
        cp = update["channel_post"]
        chat = cp.get("chat", {})
        username = chat.get("username", "")
        if f"@{username}" == CHANNEL_USERNAME or str(chat.get("id", "")) == CHANNEL_USERNAME:
            post_date = cp.get("date", 0)
            if post_date:
                _state["last_publish_ts"] = float(post_date)
                logger.info(f"📡 Channel post detected, updated last_publish_ts: {post_date}")

    if "message" in update:
        msg = update["message"]
        text = (msg.get("text") or "").strip()
        chat_id = str(msg["chat"]["id"])

        if text == "/start": cmd_start(chat_id)
        elif text == "/news":
            tg_send("⏳ Ищу лучшую новость...", chat_id=chat_id)
            send_news_digest(chat_id)
        elif text == "/interval": cmd_interval(chat_id)
        elif text == "/status": cmd_status(chat_id)
        elif text == "/help": cmd_help(chat_id)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        data = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])

        if data.startswith("int:"):
            h = float(data.split(":", 1)[1])
            _state["interval"] = int(h * 3600)
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"Интервал: {_interval_text(int(h*3600))}"})
            cmd_interval_update(chat_id, cb["message"]["message_id"])
        else:
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id})


# ============================================================
# КОМАНДЫ
# ============================================================

def cmd_start(chat_id: str):
    tg_send(f"👋 <b>Новостной бот — Корейский шоубиз</b>\n\n"
            f"<b>Интервал:</b> {_interval_text(_state['interval'])}\n"
            f"<b>Режим:</b> автопост лучшей новости с фото (8+/10)\n"
            f"<b>Канал:</b> {CHANNEL_USERNAME}\n\n"
            "<b>Команды:</b>\n/news — лучшая новость сейчас\n"
            "/interval — частота\n/status — статус таймера\n/help — справка", chat_id=chat_id)

def cmd_help(chat_id: str):
    tg_send("📖 <b>Как работает:</b>\n\n"
            f"Бот отслеживает время последнего поста в канале.\n"
            f"Когда прошло {_interval_text(_state['interval'])} — парсит RSS, "
            "находит лучшую новость (8+/10) с фото и публикует.\n\n"
            "Новости НЕ кешируются — парсинг только в момент публикации.\n\n"
            "/news — запросить сейчас\n"
            "/interval — изменить частоту\n"
            "/status — когда следующий пост", chat_id=chat_id)

def cmd_status(chat_id: str):
    """Показывает когда был последний пост и сколько до следующего."""
    last_ts = _state.get("last_publish_ts")
    if not last_ts:
        tg_send("📊 <b>Статус:</b>\n\n"
                "Последний пост: неизвестно\n"
                "Следующий пост: скоро (при первой проверке)", chat_id=chat_id)
        return

    now = time.time()
    elapsed = now - last_ts
    remaining = max(0, _state["interval"] - elapsed)

    last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if remaining == 0:
        next_text = "сейчас (ожидает следующей проверки)"
    else:
        rem_h = int(remaining // 3600)
        rem_m = int((remaining % 3600) // 60)
        next_text = f"через {rem_h}ч {rem_m}мин"

    tg_send(f"📊 <b>Статус:</b>\n\n"
            f"Последний пост: {last_dt}\n"
            f"Интервал: {_interval_text(_state['interval'])}\n"
            f"Следующий пост: {next_text}", chat_id=chat_id)

def cmd_interval(chat_id: str):
    cur = _state["interval"] / 3600
    b, r = [], []
    for h in [2, 4, 6, 8, 12]:
        label = f"{h}ч"
        sel = '✅ ' if abs(h - cur) < 0.01 else ''
        r.append({"text": f"{sel}{label}", "callback_data": f"int:{h}"})
        if len(r) == 3: b.append(r); r = []
    if r: b.append(r)
    tg_send(f"⏰ Сейчас: каждые <b>{_interval_text(_state['interval'])}</b>", reply_markup={"inline_keyboard": b}, chat_id=chat_id)

def cmd_interval_update(chat_id: str, mid: int):
    cur = _state["interval"] / 3600
    b, r = [], []
    for h in [2, 4, 6, 8, 12]:
        label = f"{h}ч"
        sel = '✅ ' if abs(h - cur) < 0.01 else ''
        r.append({"text": f"{sel}{label}", "callback_data": f"int:{h}"})
        if len(r) == 3: b.append(r); r = []
    if r: b.append(r)
    tg_api("editMessageText", {"chat_id": chat_id, "message_id": mid,
        "text": f"⏰ Сейчас: каждые <b>{_interval_text(_state['interval'])}</b>",
        "parse_mode": "HTML", "reply_markup": {"inline_keyboard": b}})


# ============================================================
# ПОТОКИ
# ============================================================

def polling_loop():
    """Polling с allowed_updates включающим channel_post для отслеживания постов."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    logger.info("🎧 Polling started (tracking channel_post + message + callback_query)")
    while True:
        try:
            resp = requests.get(url, params={
                "offset": offset,
                "timeout": 30,
                "allowed_updates": json.dumps(["message", "callback_query", "channel_post"]),
            }, timeout=35)
            if resp.status_code != 200:
                logger.error(f"Polling error {resp.status_code}"); time.sleep(5); continue
            for u in resp.json().get("result", []):
                offset = u["update_id"] + 1
                try: handle_update(u)
                except Exception as e: logger.error(f"Update error: {e}")
        except requests.exceptions.Timeout: continue
        except Exception as e: logger.error(f"Polling error: {e}"); time.sleep(5)


def scheduler_loop():
    """
    Каждые CHECK_INTERVAL секунд проверяет:
    прошло ли достаточно времени с последнего поста в канале.
    Если да — парсит новости и публикует.
    """
    logger.info("⏰ Scheduler started (checks channel post time)")
    time.sleep(30)  # даём polling стартовать первым

    while True:
        try:
            now = time.time()
            last_ts = _state.get("last_publish_ts")

            if last_ts is None:
                # Первый запуск — пробуем узнать время последнего поста
                last_ts = get_last_channel_post_time()
                if last_ts:
                    _state["last_publish_ts"] = last_ts
                    logger.info(f"📌 Initial last post time: {datetime.fromtimestamp(last_ts, tz=timezone.utc)}")
                else:
                    # Не удалось узнать — постим сразу
                    logger.info("📌 No last post time found, posting now")
                    send_news_digest()
                    time.sleep(CHECK_INTERVAL)
                    continue

            elapsed = now - last_ts
            remaining = _state["interval"] - elapsed

            if remaining <= 0:
                # Время пришло! Парсим и публикуем
                logger.info(f"⏰ Time to post! {elapsed/3600:.1f}h since last post "
                           f"(interval: {_state['interval']/3600:.1f}h)")
                send_news_digest()

                # Если публикация не обновила last_publish_ts
                # (например, нет новостей), ставим текущее время
                # чтобы не спамить попытками каждые CHECK_INTERVAL
                if _state.get("last_publish_ts") == last_ts:
                    _state["last_publish_ts"] = now
                    logger.info("⏰ No news published, resetting timer to now")
            else:
                rem_h = int(remaining // 3600)
                rem_m = int((remaining % 3600) // 60)
                logger.debug(f"⏳ Next post in {rem_h}h {rem_m}m")

        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        time.sleep(CHECK_INTERVAL)


def start():
    if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logger.warning("⚠ Bot env vars not set — bot disabled"); return
    threading.Thread(target=polling_loop, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    logger.info("🤖 News bot started (2 threads: polling, scheduler)")

start()
