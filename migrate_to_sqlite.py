"""
Скрипт миграции данных: PostgreSQL → SQLite
Запускать ОДИН РАЗ локально, когда есть доступ к обоим БД.

Использование:
  1. pip install psycopg2-binary
  2. Установи POSTGRES_URL и SQLITE_PATH ниже
  3. python migrate_to_sqlite.py
"""

import sqlite3
import os

# ── Настрой эти переменные ──
POSTGRES_URL = os.environ.get('DATABASE_URL', 'postgresql://user:pass@host:5432/dbname')
SQLITE_PATH = '/var/data/korean_learning.db'  # путь на Render Disk

# Порядок важен из-за foreign keys
TABLES = [
    'teacher',
    'student',
    'student_account',
    'note',
    'module_progress',
    'session_log',
    'section_check',
    'trainer_item_progress',
    'word_hub',
]

def migrate():
    import psycopg2
    import psycopg2.extras

    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)

    pg = psycopg2.connect(POSTGRES_URL)
    pg_cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    sl = sqlite3.connect(SQLITE_PATH)
    sl.execute("PRAGMA journal_mode=WAL")
    sl.execute("PRAGMA foreign_keys=ON")

    for table in TABLES:
        print(f"\n── {table} ──")
        try:
            pg_cur.execute(f"SELECT * FROM {table}")
        except Exception as e:
            print(f"  Пропуск (таблица не существует): {e}")
            pg.rollback()
            continue

        rows = pg_cur.fetchall()
        if not rows:
            print(f"  Пусто, пропуск")
            continue

        columns = list(rows[0].keys())
        placeholders = ','.join(['?'] * len(columns))
        cols_str = ','.join(columns)
        insert_sql = f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({placeholders})"

        count = 0
        for row in rows:
            values = [row[c] for c in columns]
            try:
                sl.execute(insert_sql, values)
                count += 1
            except Exception as e:
                print(f"  Ошибка строки: {e}")

        sl.commit()
        print(f"  Перенесено {count}/{len(rows)} строк")

    pg_cur.close()
    pg.close()
    sl.close()
    print(f"\n✅ Готово! БД сохранена: {SQLITE_PATH}")

if __name__ == '__main__':
    migrate()
