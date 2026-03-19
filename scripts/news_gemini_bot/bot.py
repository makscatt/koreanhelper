#!/usr/bin/env python3
"""
Gemini News Bot — Корейский шоубиз + Мировое кино
Парсит RSS-ленты, фильтрует через Gemini, отправляет сводку в Telegram.

Установка зависимостей (в отдельном venv!):
    pip install feedparser google-generativeai requests

Запуск вручную:
    python bot.py

Cron (каждые 4 часа):
    0 */4 * * * /home/USER/scripts/news_gemini_bot/venv/bin/python /home/USER/scripts/news_gemini_bot/bot.py >> /home/USER/scripts/news_gemini_bot/bot.log 2>&1
"""

import feedparser
import google.generativeai as genai
import requests
import datetime
import sys
import time

# ============================================================
# НАСТРОЙКИ — подставьте свои значения
# ============================================================

GEMINI_API_KEY = "ВАШ_КЛЮЧ_GEMINI"
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
TELEGRAM_CHAT_ID = "ВАШ_CHAT_ID"

# Модель Gemini (flash — быстрая и бесплатная)
GEMINI_MODEL = "gemini-1.5-flash"

# Сколько новостей брать с каждого источника
NEWS_PER_FEED = 10

# Максимальная длина сообщения Telegram (4096 символов)
TG_MAX_LENGTH = 4000

# ============================================================
# RSS-ИСТОЧНИКИ
# ============================================================

# Корейский шоубиз (K-pop, K-drama, развлекательная индустрия)
KOREAN_FEEDS = [
    "https://www.soompi.com/feed",                          # Soompi — крупнейший K-pop/K-drama портал
    "https://www.koreaboo.com/feed",                        # Koreaboo — вирусные K-pop новости
    "https://www.kpopstarz.com/rss/archives/all.xml",       # KpopStarz — новости K-pop
    "https://www.koreaherald.com/rss/kpop",                 # Korea Herald — K-pop секция
    "https://www.allkpop.com/rss",                          # AllKpop — все K-pop новости
]

# Мировое кино и киноиндустрия (Оскар, фестивали, резонансные новости)
CINEMA_FEEDS = [
    "https://variety.com/feed",                              # Variety — главный голливудский журнал
    "https://deadline.com/feed",                             # Deadline — горячие новости Голливуда
    "https://www.hollywoodreporter.com/c/movies/feed",       # Hollywood Reporter — кино
    "https://feeds.feedburner.com/slashfilm",                # /Film — кино и сериалы
]

# ============================================================
# ТЕМАТИКА ДЛЯ GEMINI
# ============================================================

TOPIC_KOREAN = (
    "Корейская индустрия развлечений: K-pop (новые релизы, скандалы, камбэки, концерты, рекорды), "
    "K-drama (новые дорамы, кастинги, рейтинги), корейские фильмы, награды, "
    "корейские знаменитости, корейская культура в мире."
)

TOPIC_CINEMA = (
    "Мировая киноиндустрия: самые резонансные новости — Оскар, Канны и другие кинопремии, "
    "громкие премьеры, бокс-офис рекорды, скандалы в Голливуде, "
    "кастинги в крупных проектах, закрытие/открытие студий, стриминговые войны (Netflix, Disney+ и т.д.)."
)


# ============================================================
# ФУНКЦИИ
# ============================================================

def log(msg: str):
    """Простой лог с временной меткой."""
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def fetch_news(feeds: list[str], label: str) -> str:
    """Собирает новости из списка RSS-лент."""
    news_text = ""
    total = 0

    for url in feeds:
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                log(f"  ⚠ Не удалось распарсить: {url}")
                continue

            source = feed.feed.get("title", url)
            for entry in feed.entries[:NEWS_PER_FEED]:
                title = entry.get("title", "").strip()
                desc = entry.get("description", "").strip()
                link = entry.get("link", "").strip()

                # Убираем HTML-теги из описания (грубо, но надёжно)
                import re
                desc = re.sub(r"<[^>]+>", "", desc)
                # Обрезаем слишком длинные описания
                if len(desc) > 500:
                    desc = desc[:500] + "..."

                news_text += (
                    f"Источник: {source}\n"
                    f"Заголовок: {title}\n"
                    f"Описание: {desc}\n"
                    f"Ссылка: {link}\n\n"
                )
                total += 1

        except Exception as e:
            log(f"  ✗ Ошибка парсинга {url}: {e}")
            continue

    log(f"  [{label}] Собрано новостей: {total}")
    return news_text


def ask_gemini(news_text: str, topic: str, section_name: str) -> str:
    """Отправляет новости в Gemini для анализа и фильтрации."""
    prompt = f"""
Ты — профессиональный редактор новостного Telegram-канала на русском языке.

Проанализируй список новостей ниже и выбери ТОЛЬКО самые интересные и резонансные,
которые касаются темы: «{topic}»

ПРАВИЛА:
1. Выбери от 3 до 7 самых важных/интересных новостей.
2. Если подходящих новостей меньше 3 — выбери сколько есть.
3. Если подходящих новостей нет — напиши одной строкой: «Новых новостей по этой теме нет.»
4. Пиши на РУССКОМ языке (переводи с английского если нужно).
5. Формат каждой новости:

<b>🔹 Заголовок</b>
Краткая суть в 1-2 предложениях.
<a href="ссылка_на_оригинал">Читать →</a>

6. Не добавляй вступление и заключение, только новости.

НОВОСТИ ДЛЯ АНАЛИЗА:
{news_text}
"""

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        log(f"  ✗ Ошибка Gemini ({section_name}): {e}")
        return ""


def send_telegram(text: str):
    """Отправляет сообщение в Telegram. Разбивает на части если слишком длинное."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Разбиваем длинные сообщения
    chunks = []
    if len(text) <= TG_MAX_LENGTH:
        chunks = [text]
    else:
        # Разбиваем по двойному переносу строки (между новостями)
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
        try:
            resp = requests.post(url, data=payload, timeout=30)
            if resp.status_code != 200:
                log(f"  ⚠ Telegram вернул {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log(f"  ✗ Ошибка отправки в Telegram: {e}")

        # Пауза между сообщениями (Telegram rate limit)
        if i < len(chunks) - 1:
            time.sleep(1)


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    log("=" * 50)
    log("🚀 Запуск Gemini News Bot")
    log("=" * 50)

    # Настраиваем Gemini
    genai.configure(api_key=GEMINI_API_KEY)

    results = []

    # --- Блок 1: Корейский шоубиз ---
    log("📡 Сбор новостей: Корейский шоубиз...")
    korean_news = fetch_news(KOREAN_FEEDS, "K-Entertainment")

    if korean_news:
        log("🤖 Обработка Gemini: Корейский шоубиз...")
        korean_summary = ask_gemini(korean_news, TOPIC_KOREAN, "Korean")
        if korean_summary and "нет" not in korean_summary.lower()[:50]:
            results.append(f"🇰🇷 <b>КОРЕЙСКИЙ ШОУБИЗ</b>\n\n{korean_summary}")
        elif korean_summary:
            results.append(f"🇰🇷 <b>КОРЕЙСКИЙ ШОУБИЗ</b>\n\n{korean_summary}")
    else:
        log("  ⚠ Корейские новости не собраны.")

    # Пауза между запросами к Gemini (чтобы не упереться в лимит)
    time.sleep(2)

    # --- Блок 2: Мировое кино ---
    log("📡 Сбор новостей: Мировое кино...")
    cinema_news = fetch_news(CINEMA_FEEDS, "Cinema")

    if cinema_news:
        log("🤖 Обработка Gemini: Мировое кино...")
        cinema_summary = ask_gemini(cinema_news, TOPIC_CINEMA, "Cinema")
        if cinema_summary and "нет" not in cinema_summary.lower()[:50]:
            results.append(f"🎬 <b>МИРОВОЕ КИНО</b>\n\n{cinema_summary}")
        elif cinema_summary:
            results.append(f"🎬 <b>МИРОВОЕ КИНО</b>\n\n{cinema_summary}")
    else:
        log("  ⚠ Киноновости не собраны.")

    # --- Отправка ---
    if results:
        today = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        header = f"📰 <b>Новостная сводка</b>  •  {today}\n{'—' * 30}\n\n"
        full_message = header + "\n\n".join(results)

        log("📤 Отправка в Telegram...")
        send_telegram(full_message)
        log("✅ Сводка отправлена!")
    else:
        log("⚠ Нечего отправлять — ни одна секция не дала результатов.")

    log("🏁 Завершено.\n")


if __name__ == "__main__":
    main()
