#!/usr/bin/env python3
"""
Gemini News Bot — Корейский шоубиз + Мировое кино
Работает ВНУТРИ Flask-приложения на Render.

Подключение: в app.py добавить:  import bot
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
# НАСТРОЙКИ
# ============================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CHANNEL_USERNAME = "@KoreanMaks"
CHANNEL_DZEN = "@KoreanMakscatt_news"
CHANNEL_LINK = "https://t.me/KoreanMaks"
GEMINI_MODEL = "gemini-3.1-pro-preview"
NEWS_PER_FEED = 10
TG_MAX_LENGTH = 4000

# ============================================================
# СОСТОЯНИЕ
# ============================================================

_state = {
    "interval": 4 * 60 * 60,
    "topics": {"korean": True, "cinema": True, "science": True},
    "news_cache": {},
    "digest_list": [],
    "last_post_text": "",
    "last_post_nid": "",
    "dzen_posted": set(),          # ID новостей уже опубликованных в Дзен
    "dzen_auto_interval": 2.5 * 60 * 60,  # автопостинг в Дзен каждые 2.5 часа
}

# ============================================================
# RSS-ИСТОЧНИКИ
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

ОЦЕНИВАЙ ПО ШКАЛЕ 1-10. Оставляй ТОЛЬКО 7-10 баллов.

ЧТО ЦЕННО (7-10 баллов):
- Новости про BTS, BLACKPINK, Stray Kids, SEVENTEEN, aespa, NewJeans и другие топовые группы (камбэки, рекорды, скандалы, мировые туры)
- Топовые актёры: Чжи Чан Ук, Ви Ха Джун, Ли Джун Ги, Сон Джун Ки, Пак Со Джун, Чон Джи Хён, Хан Со Хи, Ким Су Хён — любые новости про них
- Крупные премьеры дорам и корейских фильмов с известным кастом
- Скандалы и резонансные события (уход из группы, судебные дела, неожиданные камбэки)
- Рекорды на Billboard, Grammy, мировые чарты
- Корейское кино на международных фестивалях (Канны, Оскар, Венеция)

ЧТО МУСОР (1-6 баллов, ВЫКИДЫВАЙ):
- Малоизвестные айдолы без широкой аудитории
- Рутинные фанмитинги и мелкие ивенты
- Фандомные склоки без реального инфоповода
- Мелкие обновления без новостной ценности

АНТИКЛИКБЕЙТ-ФИЛЬТР:
- Если новость обещает «раскрыть причину» / «шокирующие подробности» / «настоящую правду», но в тексте НЕТ конкретики — это кликбейт, ставь 1 балл.
- Если суть новости сводится к «кто-то намекнул на что-то в соцсетях» без деталей — ставь 1-3 балла.
- Новость ДОЛЖНА содержать конкретный факт: что произошло, кто, когда, какой результат.
""",
        "topic_summary": "Корейский шоубиз (K-pop, K-drama, корейское кино)",
    },
    "cinema": {
        "label": "🎬 МИРОВОЕ КИНО",
        "feeds": [
            "https://variety.com/feed",
            "https://deadline.com/feed",
            "https://www.hollywoodreporter.com/c/movies/feed",
            "https://www.hollywoodreporter.com/c/tv/k-pop/feed",
            "https://feeds.feedburner.com/slashfilm",
            "https://www.indiewire.com/feed",
        ],
        "topic_filter": """
Мировая киноиндустрия.

ОЦЕНИВАЙ ПО ШКАЛЕ 1-10. Оставляй ТОЛЬКО 7-10 баллов.

ЧТО ЦЕННО (7-10 баллов):
- Оскар, Золотой глобус, Канны, Венеция — результаты, скандалы, сюрпризы
- Крупные кастинги (A-list актёры в новых проектах)
- Бокс-офис рекорды (фильм собрал $1 млрд и т.п.)
- Скандалы в Голливуде с известными именами
- Netflix/Disney+/HBO — крупные анонсы, отмены популярных шоу
- Смена руководства крупных студий (Disney, Warner, Universal)
- Сиквелы/ребуты культовых франшиз (Marvel, DC, Star Wars, Dune и т.д.)
- Аниме: крупные анонсы, рекорды, новые сезоны культовых тайтлов

ЧТО МУСОР (1-6 баллов, ВЫКИДЫВАЙ):
- Мелкие инди-фильмы без известных имён
- Рутинные кастинги в незначительных проектах
- Бизнес-новости без общественного резонанса
- Телешоу и реалити без широкого интереса

АНТИКЛИКБЕЙТ-ФИЛЬТР:
- Если новость обещает «шокирующие детали» / «неожиданный поворот», но конкретики нет — ставь 1 балл.
- Новость ДОЛЖНА содержать конкретный факт: что произошло, кто, когда, какой результат.
""",
        "topic_summary": "Мировое кино (Голливуд, кинопремии, стриминги)",
    },
    "science": {
        "label": "🔬 НАУКА И ТЕХНОЛОГИИ",
        "feeds": [
            "https://www.nature.com/nature.rss",
            "https://www.science.org/rss/news_current.xml",
            "https://newatlas.com/feed/",
            "https://arstechnica.com/feed/",
            "https://phys.org/rss-feed/",
            "https://www.sciencedaily.com/rss/all.xml",
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        ],
        "topic_filter": """
Наука, технологии, необычные открытия и изобретения.

ОЦЕНИВАЙ ПО ШКАЛЕ 1-10. Оставляй ТОЛЬКО 7-10 баллов.

ЧТО ЦЕННО (7-10 баллов):
- Прорывные научные открытия (новое лекарство, новый вид, квантовые компьютеры, космос)
- Необычные истории из мира науки (человек сам создал лекарство для своей собаки, кто-то собрал устройство из подручных средств)
- Технологические прорывы (новые процессоры, достижения в ИИ, роботы, энергетика)
- Космос: запуски, открытия, миссии
- Крупные медицинские новости (вакцины, методы лечения, эпидемии)
- Самодельные проекты и изобретения обычных людей
- Экология и климат — только если есть конкретный повод

ЧТО МУСОР (1-6 баллов, ВЫКИДЫВАЙ):
- Рутинные публикации без открытия («учёные изучили» без результата)
- Переписывание пресс-релизов компаний без новизны
- Общие рассуждения о будущем технологий без конкретики
- Мелкие обновления программ и устройств

АНТИКЛИКБЕЙТ-ФИЛЬТР:
- «Учёные обнаружили удивительное свойство» — БЕЗ описания свойства = 1 балл.
- «Новое исследование может изменить всё» — БЕЗ деталей = 1 балл.
- Новость ДОЛЖНА содержать конкретный факт: что открыли/изобрели, как работает, какой результат.

БОНУС: истории типа «инженер собрал мессенджер, который работает без интернета» или «ветеринар сам разработал лекарство от рака для собаки» — это 9-10 баллов. Необычные, конкретные, с человеческой историей.
""",
        "topic_summary": "Наука, технологии, необычные открытия",
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
- Научные и технические термины ВСЕГДА объясняй через простые аналогии. Не «ротоскопирование», а «художники рисовали поверх живых кадров». Не «рекуррентная нейросеть», а «программа, которая запоминает предыдущие шаги».
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

ПРИМЕРЫ ХОРОШЕГО СТИЛЯ:

🌾 Генетики учат рис расти годами без пересадки
Обычный рис живёт один сезон — каждый год его сажают заново. Учёные взяли гены у диких родственников риса, которые растут сами по себе десятилетиями, и перенесли их в обычные сорта. Идея простая: посадил один раз — собираешь урожай много лет подряд, как с яблони.

👁️ Элайджа Вуд только сейчас начал читать «Властелина колец»
Спустя 23 года после съёмок актёр, сыгравший Фродо, наконец добрался до книги — рассказал об этом на The Late Show. Назвал её «восхитительной». Возможно, готовится к возвращению в «Охоте на Голлума».

🕷 Трейлер «Человека-паука» побил мировой рекорд
Ролик Spider-Man: Brand New Day набрал 718,6 млн просмотров за первые сутки — почти вдвое больше «Дэдпула и Росомахи» (365 млн).

🦠 Новый фильм от создателя «Поезда в Пусан»
Ён Сан-хо снимает «Колонию» — по сюжету вирус запирает людей в здании, а заражённые начинают меняться. В главных ролях Чон Джи-хён и Ку Гё-хван.

💿 Пластинка по «Паддингтону» с мармеладом внутри
На виниле записан саундтрек лондонского мюзикла. Внутри пластинки залита оранжевая жидкость — как любимый мармелад Паддингтона. Выпускает Blood Records, они делают такие необычные издания.

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
    h = s // 3600
    return "1 час" if h == 1 else f"{h} часа" if h < 5 else f"{h} часов"


def _find_image_for(nid: str) -> str:
    """Ищет фото для новости. Сначала в самой записи, потом по похожим заголовкам в кэше."""
    item = _state["news_cache"].get(nid, {})
    if item.get("image"):
        return item["image"]

    # Ищем среди всех записей в кэше по похожему заголовку
    title = item.get("title", "").lower()
    if not title:
        return ""

    # Берём ключевые слова из заголовка (слова длиннее 4 символов)
    keywords = [w for w in re.split(r'\W+', title) if len(w) > 4]
    if not keywords:
        return ""

    best_match = ""
    best_score = 0

    for other_id, other in _state["news_cache"].items():
        if other_id == nid or not other.get("image"):
            continue
        other_title = other.get("title", "").lower()
        # Считаем совпадения ключевых слов
        score = sum(1 for kw in keywords if kw in other_title)
        if score > best_score and score >= 2:  # минимум 2 совпадения
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
                # Если такой ID уже в кэше без фото, а сейчас фото есть — обновить
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

    prompt = f"""
Ты — строгий редактор новостного канала. Твоя задача — отобрать ТОЛЬКО по-настоящему важные и резонансные новости.

ТЕМАТИКА И КРИТЕРИИ ОЦЕНКИ:
{topic_filter}

ИНСТРУКЦИЯ:
1. Оцени КАЖДУЮ новость по шкале 1-10.
2. ВЫКИНЬ всё что ниже 7.
3. Оставшиеся отсортируй от высшего балла к низшему.
4. Оставь максимум 5 новостей.

ВЕРНИ СТРОГО JSON (без markdown, без ```):
[
  {{
    "id": "ID новости",
    "score": 9,
    "headline": "Краткий заголовок на русском (до 80 символов)",
    "summary": "Суть в 1-2 предложениях на русском"
  }}
]

Если ни одна новость не набрала 7+, верни: []

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
        # Доп. фильтр на случай если Gemini проигнорировала порог
        return [r for r in result if r.get("score", 0) >= 7]
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

        # Если Gemini определил кликбейт
        if text.upper().startswith("SKIP"):
            return "SKIP"

        # Убираем ссылки если Gemini их вставила
        text = re.sub(r'Оригинал\s*\(?\s*https?://[^\s\)]+\)?\s*', '', text).strip()
        text = re.sub(r'https?://\S+', '', text).strip()

        # Пустая строка между каждым абзацем (заголовок, абзац1, абзац2...)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n\n'.join(lines)

        # Ссылка на канал
        text += f'\n\n<a href="{CHANNEL_LINK}">Подписаться на KoreanMaks 🔥🚀🇰🇷</a>'
        return text
    except Exception as e:
        logger.error(f"Gemini post error: {e}")
        return f"❌ Ошибка генерации: {e}"


# ============================================================
# СВОДКА — ОТДЕЛЬНОЕ СООБЩЕНИЕ НА КАЖДЫЙ БЛОК
# ============================================================

def send_news_digest(chat_id: str = None):
    cid = chat_id or TELEGRAM_CHAT_ID
    logger.info("🚀 News digest started")

    today = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    active_topics = {k: v for k, v in FEEDS.items() if _state["topics"].get(k, True)}

    if not active_topics:
        tg_send("⚠ Все тематики выключены. /topics", chat_id=cid)
        return

    tg_send(f"📰 <b>Новостная сводка</b>  •  {today}", chat_id=cid)

    digest_list = []
    counter = 1

    for key, config in active_topics.items():
        logger.info(f"Fetching {key}...")
        items = fetch_news(config["feeds"], key)
        if not items:
            continue

        digest_items = gemini_digest(items, config["topic_filter"])
        if not digest_items:
            tg_send(f"\n<b>{config['label']}</b>\n\n🤷 Ничего достойного не найдено (все новости ниже 7 баллов).", chat_id=cid)
            time.sleep(1)
            continue

        # Формируем сообщение для этого блока
        lines = [f"<b>{config['label']}</b>\n"]

        for item in digest_items:
            nid = item.get("id", "")
            score = item.get("score", "?")
            headline = item.get("headline", "—")
            summary = item.get("summary", "")

            lines.append(f"<b>{counter}.</b> [{score}/10] <b>{headline}</b>\n{summary}\n")
            digest_list.append({"num": counter, "id": nid, "headline": headline, "summary": summary, "score": score})
            counter += 1

        lines.append(f"{'—' * 25}")
        lines.append("Пост: <code>/post номер</code>")

        block_text = "\n".join(lines)
        tg_send(block_text, chat_id=cid)
        time.sleep(2)

    _state["digest_list"] = digest_list

    if counter == 1:
        tg_send("🤷 Ни одна новость не прошла фильтр качества.", chat_id=cid)

    logger.info(f"✅ Digest sent! {counter - 1} items (7+ score)")


# ============================================================
# ОБРАБОТКА
# ============================================================

def handle_update(update: dict):
    if "message" in update:
        msg = update["message"]
        text = (msg.get("text") or "").strip()
        chat_id = str(msg["chat"]["id"])

        if text == "/start": cmd_start(chat_id)
        elif text == "/news":
            tg_send("⏳ Собираю новости...", chat_id=chat_id)
            send_news_digest(chat_id)
        elif text.startswith("/post"): cmd_post(text, chat_id)
        elif text == "/topics": cmd_topics(chat_id)
        elif text == "/interval": cmd_interval(chat_id)
        elif text == "/help": cmd_help(chat_id)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        data = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])

        if data.startswith("rewrite:"):
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "⏳ Переписываю..."})
            nid = data.split(":", 1)[1]
            news_item = _state["news_cache"].get(nid)
            if news_item:
                post_text = gemini_post(news_item["title"], news_item["description"], news_item["link"], bool(_find_image_for(nid)))
                if post_text == "SKIP":
                    tg_send("🚫 Кликбейт — нечего переписывать.", chat_id=chat_id)
                else:
                    _state["last_post_text"] = post_text
                    _state["last_post_nid"] = nid
                    tg_send(f"✅ <b>Новый вариант:</b>\n\n{post_text}", reply_markup=_post_buttons(nid), chat_id=chat_id)

        elif data.startswith("pub_photo:"):
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "📤 Публикую..."})
            _publish(data.split(":", 1)[1], True, chat_id)

        elif data.startswith("pub_text:"):
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "📤 Публикую..."})
            _publish(data.split(":", 1)[1], False, chat_id)

        elif data.startswith("dzen_photo:"):
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "📤 В Дзен..."})
            _publish_dzen(data.split(":", 1)[1], True, chat_id)

        elif data.startswith("dzen_text:"):
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": "📤 В Дзен..."})
            _publish_dzen(data.split(":", 1)[1], False, chat_id)

        elif data.startswith("topic:"):
            key = data.split(":", 1)[1]
            if key in _state["topics"]:
                _state["topics"][key] = not _state["topics"][key]
                tg_api("answerCallbackQuery", {"callback_query_id": cb_id,
                    "text": f"{'✅ вкл' if _state['topics'][key] else '❌ выкл'}"})
                cmd_topics_update(chat_id, cb["message"]["message_id"])

        elif data.startswith("int:"):
            h = int(data.split(":", 1)[1])
            _state["interval"] = h * 3600
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"Интервал: {_interval_text(h*3600)}"})
            cmd_interval_update(chat_id, cb["message"]["message_id"])

        else:
            tg_api("answerCallbackQuery", {"callback_query_id": cb_id})


# ============================================================
# /post ID
# ============================================================

def cmd_post(text: str, chat_id: str):
    parts = text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        tg_send("Использование: <code>/post номер</code>\nПример: <code>/post 3</code>", chat_id=chat_id)
        return

    num = int(parts[1])
    item = next((d for d in _state.get("digest_list", []) if d["num"] == num), None)

    if not item:
        total = len(_state.get("digest_list", []))
        tg_send(f"❌ #{num} не найден. Доступно: 1-{total}" if total else "Сводка пуста. /news", chat_id=chat_id)
        return

    nid = item["id"]
    news_item = _state["news_cache"].get(nid)
    if not news_item:
        tg_send("❌ Кэш устарел. /news", chat_id=chat_id)
        return

    tg_send(f"⏳ Генерирую пост #{num}...", chat_id=chat_id)

    image_url = _find_image_for(nid)
    post_text = gemini_post(news_item["title"], news_item["description"], news_item["link"], bool(image_url))

    if post_text == "SKIP":
        tg_send(f"🚫 Пост #{num} отклонён — кликбейт без содержания. Попробуй другую новость.", chat_id=chat_id)
        return

    _state["last_post_text"] = post_text
    _state["last_post_nid"] = nid

    markup = _post_buttons(nid)

    if image_url:
        tg_send_photo(image_url, f"✅ Пост #{num}:\n\n{post_text}", reply_markup=markup, chat_id=chat_id)
    else:
        tg_send(f"✅ <b>Пост #{num}:</b>\n\n{post_text}", reply_markup=markup, chat_id=chat_id)


def _post_buttons(nid: str) -> dict:
    has_img = bool(_find_image_for(nid))
    buttons = []
    if has_img:
        buttons.append([{"text": "📷 Опубликовать с фото", "callback_data": f"pub_photo:{nid}"}])
    buttons.append([{"text": "📝 Опубликовать без фото", "callback_data": f"pub_text:{nid}"}])
    if has_img:
        buttons.append([{"text": "📤 Только в Дзен с фото", "callback_data": f"dzen_photo:{nid}"}])
    buttons.append([{"text": "📤 Только в Дзен без фото", "callback_data": f"dzen_text:{nid}"}])
    buttons.append([{"text": "🔄 Переписать", "callback_data": f"rewrite:{nid}"}])
    return {"inline_keyboard": buttons}


def _publish(nid: str, with_photo: bool, chat_id: str):
    post_text = _state.get("last_post_text", "")
    news_item = _state["news_cache"].get(nid, {})
    if not post_text:
        tg_send("❌ Нет поста. Сначала /post номер", chat_id=chat_id); return

    image_url = _find_image_for(nid)

    # Текст для Дзена — без ссылки на канал
    dzen_text = re.sub(r'\n\n<a href="[^"]*">Подписаться на KoreanMaks[^<]*</a>', '', post_text).strip()

    # --- Публикация в основной канал (с ссылкой на подписку) ---
    if with_photo and image_url:
        result = tg_send_photo(image_url, post_text, chat_id=CHANNEL_USERNAME)
    else:
        result = tg_api("sendMessage", {"chat_id": CHANNEL_USERNAME, "text": post_text, "parse_mode": "HTML", "disable_web_page_preview": False})

    # --- Публикация в Дзен-канал (без ссылки на подписку) ---
    if with_photo and image_url:
        tg_send_photo(image_url, dzen_text, chat_id=CHANNEL_DZEN)
    else:
        tg_api("sendMessage", {"chat_id": CHANNEL_DZEN, "text": dzen_text, "parse_mode": "HTML", "disable_web_page_preview": False})

    if result and result.get("ok"):
        _state["dzen_posted"].add(nid)
        tg_send(f"✅ Опубликовано в {CHANNEL_USERNAME} + Дзен!", chat_id=chat_id)
    else:
        tg_send(f"❌ Ошибка. Бот должен быть админом обоих каналов.", chat_id=chat_id)


def _publish_dzen(nid: str, with_photo: bool, chat_id: str):
    """Публикация ТОЛЬКО в Дзен-канал."""
    post_text = _state.get("last_post_text", "")
    if not post_text:
        tg_send("❌ Нет поста. Сначала /post номер", chat_id=chat_id); return

    image_url = _find_image_for(nid)

    # Текст без ссылки на канал
    dzen_text = re.sub(r'\n\n<a href="[^"]*">Подписаться на KoreanMaks[^<]*</a>', '', post_text).strip()

    if with_photo and image_url:
        result = tg_send_photo(image_url, dzen_text, chat_id=CHANNEL_DZEN)
    else:
        result = tg_api("sendMessage", {"chat_id": CHANNEL_DZEN, "text": dzen_text, "parse_mode": "HTML", "disable_web_page_preview": False})

    if result and result.get("ok"):
        _state["dzen_posted"].add(nid)
        tg_send(f"✅ Опубликовано только в Дзен!", chat_id=chat_id)
    else:
        tg_send(f"❌ Ошибка. Бот должен быть админом {CHANNEL_DZEN}.", chat_id=chat_id)


def _send_to_dzen(nid: str, post_text: str, with_photo: bool) -> bool:
    """Отправка в Дзен-канал (без уведомлений). Возвращает True если ок."""
    image_url = _find_image_for(nid)
    dzen_text = re.sub(r'\n\n<a href="[^"]*">Подписаться на KoreanMaks[^<]*</a>', '', post_text).strip()

    if with_photo and image_url:
        result = tg_send_photo(image_url, dzen_text, chat_id=CHANNEL_DZEN)
    else:
        result = tg_api("sendMessage", {"chat_id": CHANNEL_DZEN, "text": dzen_text, "parse_mode": "HTML", "disable_web_page_preview": False})

    if result and result.get("ok"):
        _state["dzen_posted"].add(nid)
        return True
    return False


def auto_dzen_post():
    """Автопостинг в Дзен: берёт лучшую непопубликованную новость, генерит пост, отправляет."""
    logger.info("📤 Dzen auto-post started")

    # Собираем свежие новости если кэш пустой
    if not _state["news_cache"]:
        for key, config in FEEDS.items():
            if _state["topics"].get(key, True):
                fetch_news(config["feeds"], key)

    # Проходим по всем активным тематикам, собираем кандидатов
    candidates = []
    for key, config in FEEDS.items():
        if not _state["topics"].get(key, True):
            continue

        items = [item for item in _state["news_cache"].values()
                 if item.get("section") == key and item["id"] not in _state["dzen_posted"]]

        if not items:
            # Подтянем свежие
            items = fetch_news(config["feeds"], key)
            items = [i for i in items if i["id"] not in _state["dzen_posted"]]

        if not items:
            continue

        # Прогоняем через Gemini фильтр
        digest = gemini_digest(items, config["topic_filter"])
        for d in digest:
            if d.get("id") not in _state["dzen_posted"]:
                candidates.append(d)

    if not candidates:
        logger.info("📤 Dzen auto-post: нет новых новостей для публикации")
        return

    # Берём топ-1 по скору
    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    best = candidates[0]
    nid = best["id"]
    news_item = _state["news_cache"].get(nid)

    if not news_item:
        logger.warning(f"📤 Dzen auto-post: news {nid} not in cache")
        return

    # Генерируем пост
    has_photo = bool(_find_image_for(nid))
    post_text = gemini_post(news_item["title"], news_item["description"], news_item["link"], has_photo)

    if post_text == "SKIP":
        logger.info(f"📤 Dzen auto-post: SKIP (clickbait) — {news_item['title'][:50]}")
        _state["dzen_posted"].add(nid)  # чтобы не пытаться снова
        return

    # Отправляем
    success = _send_to_dzen(nid, post_text, has_photo)

    if success:
        logger.info(f"📤 Dzen auto-post OK: {news_item['title'][:50]}")
        # Уведомляем владельца
        tg_send(f"🤖 <b>Автопост в Дзен:</b>\n\n{best.get('headline', '')}\n\n<i>(оценка: {best.get('score', '?')}/10)</i>")
    else:
        logger.error("📤 Dzen auto-post FAILED")


# ============================================================
# КОМАНДЫ
# ============================================================

def cmd_start(chat_id: str):
    st = ""
    for k, c in FEEDS.items():
        st += f"  {'✅' if _state['topics'].get(k) else '❌'} {c['label']}\n"
    tg_send(f"👋 <b>Новостной бот</b>\n\n<b>Тематики:</b>\n{st}\n"
            f"<b>Интервал:</b> {_interval_text(_state['interval'])}\n"
            f"<b>Фильтр:</b> только новости с оценкой 7+/10\n\n"
            "<b>Команды:</b>\n/news — сводка\n/post <i>номер</i> — пост\n"
            "/topics — тематики\n/interval — частота\n/help — справка", chat_id=chat_id)

def cmd_help(chat_id: str):
    tg_send("📖 <b>Как пользоваться:</b>\n\n"
            "1️⃣ Приходит сводка с оценками [7-10/10]\n"
            "2️⃣ <code>/post 3</code> — пост по новости №3\n"
            "3️⃣ <b>📷 С фото</b> / <b>📝 Без фото</b> → публикация в канал\n"
            "4️⃣ <b>🔄 Переписать</b> — новый вариант", chat_id=chat_id)

def cmd_topics(chat_id: str):
    b = [[{"text": f"{'✅' if _state['topics'].get(k) else '❌'} {c['label']}", "callback_data": f"topic:{k}"}] for k, c in FEEDS.items()]
    tg_send("⚙️ <b>Тематики</b>\n\nНажмите:", reply_markup={"inline_keyboard": b}, chat_id=chat_id)

def cmd_topics_update(chat_id: str, mid: int):
    b = [[{"text": f"{'✅' if _state['topics'].get(k) else '❌'} {c['label']}", "callback_data": f"topic:{k}"}] for k, c in FEEDS.items()]
    tg_api("editMessageText", {"chat_id": chat_id, "message_id": mid,
        "text": "⚙️ <b>Тематики</b>\n\nНажмите:", "parse_mode": "HTML", "reply_markup": {"inline_keyboard": b}})

def cmd_interval(chat_id: str):
    cur = _state["interval"] // 3600
    b, r = [], []
    for h in [1, 2, 4, 6, 8, 12]:
        r.append({"text": f"{'✅ ' if h == cur else ''}{h}ч", "callback_data": f"int:{h}"})
        if len(r) == 3: b.append(r); r = []
    if r: b.append(r)
    tg_send(f"⏰ Сейчас: каждые <b>{_interval_text(_state['interval'])}</b>", reply_markup={"inline_keyboard": b}, chat_id=chat_id)

def cmd_interval_update(chat_id: str, mid: int):
    cur = _state["interval"] // 3600
    b, r = [], []
    for h in [1, 2, 4, 6, 8, 12]:
        r.append({"text": f"{'✅ ' if h == cur else ''}{h}ч", "callback_data": f"int:{h}"})
        if len(r) == 3: b.append(r); r = []
    if r: b.append(r)
    tg_api("editMessageText", {"chat_id": chat_id, "message_id": mid,
        "text": f"⏰ Сейчас: каждые <b>{_interval_text(_state['interval'])}</b>",
        "parse_mode": "HTML", "reply_markup": {"inline_keyboard": b}})


# ============================================================
# ПОТОКИ
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
    time.sleep(30)
    try: send_news_digest()
    except Exception as e: logger.error(f"First digest error: {e}")
    while True:
        time.sleep(_state["interval"])
        try: send_news_digest()
        except Exception as e: logger.error(f"Scheduled digest error: {e}")

def dzen_autopost_loop():
    """Автопостинг в Дзен каждые 2.5 часа."""
    logger.info("📤 Dzen autopost loop started")
    # Первый автопост через 1 час (дать время собрать кэш)
    time.sleep(60 * 60)
    while True:
        try:
            auto_dzen_post()
        except Exception as e:
            logger.error(f"Dzen autopost error: {e}")
        time.sleep(_state["dzen_auto_interval"])

def start():
    if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logger.warning("⚠ Bot env vars not set — bot disabled"); return
    threading.Thread(target=polling_loop, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=dzen_autopost_loop, daemon=True).start()
    logger.info("🤖 News bot started (3 threads: polling, digest, dzen autopost)")

start()
