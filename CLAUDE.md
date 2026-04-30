<!-- jarvis-claude-md-version: 4 -->
Если рядом лежит `BOSS.md` — прочти и следуй его инструкциям дополнительно
(значит у тебя есть особая роль сверх локального клода).

Общайся кратко, отвечай строго по сути вопроса. Всё что надо — я спрошу сам.

# Система отчётности (Jarvis)

В папке `reports/` лежат задачи и отчёты сессий. Папка должна быть в `.gitignore`
(если нет — добавь строку `reports/` в `.gitignore`, создай файл если нужно).

## reports/tasks.json — единый источник задач

В начале сессии прочитай этот файл, чтобы понять что открыто.

Структура:
```json
{
  "tasks": [
    {
      "id": 1,
      "title": "краткое название",
      "description": "подробности",
      "priority": "high|mid|low",
      "status": "open|done",
      "added_by": "boss|session",
      "added_at": "YYYY-MM-DD",
      "closed_at": null,
      "closed_in_session": null
    }
  ],
  "last_session_summary": "1-2 строки: что было в прошлый раз",
  "next_step": "с чего начинать в следующий раз"
}
```

Правила правки `tasks.json`:
- **Можно менять:** `status` (open→done), `closed_at`, `closed_in_session`,
  `last_session_summary`, `next_step`.
- **Можно добавлять** новые задачи (если всплыли в сессии) с
  `added_by: "session"`, уникальный `id` (max существующий + 1).
- **Нельзя трогать** у существующих задач: `title`, `description`, `priority`,
  `added_by`, `added_at` — этим владеет пользователь (босс).

## reports/sessions/session_YYYY-MM-DD_HHMM.json — отчёт сессии

Пиши **только** когда пользователь скажет «составь отчёт». Это финал сессии,
после него диалог закрывается.

Структура:
```json
{
  "date": "YYYY-MM-DD HH:MM",
  "duration_min": 45,
  "tasks_closed": [{"id": 3, "priority": "high"}],
  "tasks_added": 2,
  "difficulty": 3,
  "kind": "feature|fix|refactor|research|stuck",
  "note": "субъективно: продуктивно / тупняк / прорыв"
}
```

- `difficulty` — 1..5, твоя субъективная оценка сложности сессии.
- `kind` — преобладающий характер работы.
- `duration_min` — примерная длительность активной работы.
- XP не считай — босс посчитает сам по единой формуле.

При составлении отчёта одновременно обнови в `tasks.json`:
`last_session_summary`, `next_step`, статусы закрытых задач.
