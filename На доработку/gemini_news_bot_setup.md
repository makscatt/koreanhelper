# 🚀 Инструкция: Подселение фонового бота (Gemini News) на рабочий сервер

**Концепция:** Мы размещаем скрипт для парсинга новостей на том же сервере, где работает основной проект (Techercab). Чтобы скрипт не сломал зависимости Flask-приложения и не «повесил» веб-сервер, мы выносим его в отдельную папку, создаём изолированное виртуальное окружение (venv) и запускаем по расписанию через системный планировщик Cron.

---

## 📋 Подготовка

Перед началом работы убедитесь, что у вас есть:

- Ключ API от Google Gemini (`GEMINI_API_KEY`).
- Токен Telegram-бота от @BotFather (`TELEGRAM_BOT_TOKEN`).
- Ваш личный Telegram ID (`TELEGRAM_CHAT_ID`), куда бот будет слать сводку (можно узнать у @userinfobot).
- Доступ к серверу по SSH.

---

## Шаг 1. Создание структуры и изоляция

Подключаемся к серверу по SSH и создаём папку для нашего скрипта рядом с основным проектом (или в домашней директории).

```bash
# 1. Переходим в домашнюю директорию пользователя
cd ~

# 2. Создаем папку для утилит и переходим в нее
mkdir -p scripts/news_gemini_bot
cd scripts/news_gemini_bot

# 3. Создаем изолированное виртуальное окружение
python3 -m venv venv

# 4. Активируем его (появится приписка (venv) в консоли)
source venv/bin/activate

# 5. Устанавливаем библиотеки ТОЛЬКО для этого бота
pip install feedparser google-generativeai requests
```

---

## Шаг 2. Создание скрипта

Находясь в папке `news_gemini_bot`, создаём файл бота:

```bash
nano bot.py
```

Вставляем туда следующий код (не забудьте подставить свои ключи):

```python
import feedparser
import google.generativeai as genai
import requests
import datetime
import sys

# === НАСТРОЙКИ ===
GEMINI_API_KEY = "ВАШ_КЛЮЧ_GEMINI"
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
TELEGRAM_CHAT_ID = "ВАШ_CHAT_ID"

# Тематика для нейросети
TOPIC = "Искусственный интеллект, IT-бизнес и технологии"

# RSS-ленты для парсинга (можно добавить свои)
RSS_URLS = [
    "https://vc.ru/rss",
    "https://lenta.ru/rss/news"
]
# =================

def send_telegram_message(text):
    """Отправка сообщения в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True  # Чтобы ссылки не создавали огромные превью
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

def main():
    print(f"[{datetime.datetime.now()}] Запуск сбора новостей...")

    # 1. Собираем новости
    news_text = ""
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:  # Берем 10 свежих новостей с каждого сайта
                news_text += (
                    f"Заголовок: {entry.title}\n"
                    f"Описание: {entry.get('description', '')}\n"
                    f"Ссылка: {entry.link}\n\n"
                )
        except Exception as e:
            print(f"Ошибка парсинга {url}: {e}")
            continue

    if not news_text:
        print("Новости не собраны. Завершение.")
        sys.exit()

    # 2. Отправляем в Gemini
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""
    Ты профессиональный редактор. Проанализируй эти новости и выбери только те,
    которые касаются темы: "{TOPIC}".
    Если таких новостей нет, напиши "Новых новостей по вашей теме нет".
    Если есть, сделай красивую выжимку для Telegram. Формат для каждой новости:
    <b>Заголовок</b>
    Краткая суть в 1-2 предложениях.
    <a href="ссылка">Читать оригинал</a>

    Новости для анализа:
    {news_text}
    """

    try:
        response = model.generate_content(prompt)
        summary = response.text

        # 3. Отправляем результат
        send_telegram_message(summary)
        print("Сводка успешно отправлена!")

    except Exception as e:
        print(f"Ошибка генерации Gemini: {e}")

if __name__ == "__main__":
    main()
```

Сохраняем и закрываем файл: `Ctrl+O` → `Enter` → `Ctrl+X`.

---

## Шаг 3. Ручное тестирование

Оставаясь в виртуальном окружении, запускаем скрипт вручную, чтобы проверить, что всё работает и ключи указаны верно:

```bash
python bot.py
```

Если ошибок нет, в консоли появится `"Сводка успешно отправлена!"`, а в Telegram придёт сообщение.

После проверки выходим из виртуального окружения:

```bash
deactivate
```

---

## Шаг 4. Настройка автоматизации (Cron)

Теперь настроим сервер так, чтобы он запускал этот скрипт сам.

Для Cron нам понадобятся абсолютные пути. Узнать ваш текущий путь можно командой:

```bash
pwd
# Пример ответа: /home/user/scripts/news_gemini_bot
```

Открываем планировщик задач:

```bash
crontab -e
```

> Если сервер спросит, какой редактор использовать, нажмите цифру, соответствующую `nano`.

Прокручиваем в самый низ файла и добавляем строку (замените `/home/user/...` на ваш путь, который выдала команда `pwd`):

```text
# Запуск бота с новостями каждые 4 часа
0 */4 * * * /home/user/scripts/news_gemini_bot/venv/bin/python /home/user/scripts/news_gemini_bot/bot.py >> /home/user/scripts/news_gemini_bot/bot.log 2>&1
```

**Что делает эта команда:**

- `0 */4 * * *` — запускать ровно в 00:00, 04:00, 08:00 и т.д. (по времени сервера).
- `/.../venv/bin/python` — использует Python именно из нашего изолированного окружения (поэтому Flask-проект в безопасности).
- `/.../bot.py` — путь к нашему скрипту.
- `>> /.../bot.log 2>&1` — записывает все принты и ошибки в файл `bot.log`, чтобы мы могли их прочитать, если что-то сломается.

Сохраняем и закрываем: `Ctrl+O` → `Enter` → `Ctrl+X`.

---

## 🛠 Поддержка и мониторинг

Если бот перестал присылать новости, зайдите на сервер и проверьте лог-файл:

```bash
cd ~/scripts/news_gemini_bot
tail -n 50 bot.log
```

Эта команда покажет 50 последних строк из файла логов, где вы увидите, почему произошла ошибка (например, закончились лимиты API или изменился формат RSS).

---

> **Поздравляем!** Ваш сервер теперь не только обучает студентов, но и работает вашим личным новостным аналитиком 🤖
