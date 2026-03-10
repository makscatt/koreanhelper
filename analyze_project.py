#!/usr/bin/env python3
"""
Универсальный анализатор проекта.
Сканирует любой проект и собирает полную карту для передачи в LLM.

Использование:
    python analyze_project.py [путь]           — анализ с выводом в файл
    python analyze_project.py [путь] --stdout   — вывод в консоль
    python analyze_project.py                   — анализ текущей папки

Результат: project_analysis.txt в корне проекта.
"""

import os
import sys
import re
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════════════

# Расширения файлов для анализа (язык → расширения)
LANG_EXTENSIONS = {
    "python":     [".py"],
    "javascript": [".js", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx"],
    "jsx":        [".jsx"],
    "html":       [".html", ".htm", ".jinja", ".jinja2", ".ejs", ".hbs", ".pug"],
    "css":        [".css", ".scss", ".sass", ".less"],
    "json":       [".json"],
    "yaml":       [".yaml", ".yml"],
    "toml":       [".toml"],
    "ini":        [".ini", ".cfg", ".env"],
    "sql":        [".sql"],
    "shell":      [".sh", ".bash"],
    "markdown":   [".md"],
    "docker":     ["Dockerfile", ".dockerignore"],
    "go":         [".go"],
    "ruby":       [".rb"],
    "php":        [".php"],
    "java":       [".java"],
    "csharp":     [".cs"],
    "rust":       [".rs"],
    "vue":        [".vue"],
    "svelte":     [".svelte"],
}

# Специальные файлы, которые всегда включаем (без учёта расширения)
SPECIAL_FILES = {
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "Makefile", "Procfile", "Vagrantfile",
    ".gitignore", ".dockerignore", ".env.example", ".env.sample",
    "README.md", "README.rst", "CHANGELOG.md",
}

# Файлы зависимостей — читаем содержимое
DEPENDENCY_FILES = {
    "requirements.txt", "requirements-dev.txt", "requirements_dev.txt",
    "Pipfile", "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "composer.json", "Gemfile", "go.mod", "Cargo.toml",
}

# Папки, которые пропускаем
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv", "env", ".env",
    ".idea", ".vscode", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".next", ".nuxt", ".output", ".svelte-kit",
    "migrations", "alembic", "vendor", "bower_components",
    ".terraform", ".serverless", "coverage", "htmlcov",
    ".eggs", "*.egg-info", "site-packages", "lib", "lib64",
    "static/vendor", "static/lib", "assets/vendor",
}

# Файлы, которые пропускаем
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "composer.lock",
    ".DS_Store", "Thumbs.db",
}

# Максимальный размер файла для чтения (500 КБ)
MAX_FILE_SIZE = 500_000

# Собираем все расширения
ALL_EXTENSIONS = set()
for exts in LANG_EXTENSIONS.values():
    ALL_EXTENSIONS.update(exts)


# ═══════════════════════════════════════════════════════════════════════
# СБОР ФАЙЛОВ
# ═══════════════════════════════════════════════════════════════════════

def should_skip_dir(dir_name, dir_path_parts):
    """Проверяет, нужно ли пропустить директорию."""
    if dir_name in SKIP_DIRS:
        return True
    if dir_name.startswith(".") and dir_name not in (".github", ".gitlab"):
        return True
    if dir_name.endswith(".egg-info"):
        return True
    return False


def collect_files(root_dir):
    """Собирает все релевантные файлы проекта."""
    files = []
    root = Path(root_dir).resolve()

    for path in sorted(root.rglob("*")):
        # Пропускаем директории из SKIP_DIRS
        if any(should_skip_dir(part, path.parts) for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.name in SKIP_FILES:
            continue
        # Берём файл если подходит расширение или имя
        if path.suffix in ALL_EXTENSIONS or path.name in SPECIAL_FILES or path.name in DEPENDENCY_FILES:
            files.append(path)

    return files


def get_file_language(path):
    """Определяет язык файла."""
    for lang, exts in LANG_EXTENSIONS.items():
        if path.suffix in exts or path.name in exts:
            return lang
    return "other"


# ═══════════════════════════════════════════════════════════════════════
# АНАЛИЗАТОРЫ: PYTHON
# ═══════════════════════════════════════════════════════════════════════

def analyze_python_imports(content):
    """Извлекает импорты."""
    imports = []
    for m in re.finditer(r"^(?:from\s+([\w.]+)\s+)?import\s+(.+)", content, re.MULTILINE):
        module = m.group(1) or ""
        names = m.group(2).strip()
        if module:
            imports.append(f"from {module} import {names}")
        else:
            imports.append(f"import {names}")
    return imports


def analyze_python_structure(content, filepath):
    """Извлекает классы, функции и их docstrings."""
    items = []

    # Классы
    for m in re.finditer(
        r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:[ \t]*\n(?:\s+(?:\"\"\"([\s\S]*?)\"\"\"|\'''([\s\S]*?)\'''))?",
        content, re.MULTILINE
    ):
        name = m.group(1)
        bases = m.group(2) or ""
        doc = (m.group(3) or m.group(4) or "").strip()
        # Собираем методы класса
        class_end = _find_block_end(content, m.start())
        class_body = content[m.start():class_end]
        methods = []
        for mm in re.finditer(
            r"^\s+(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)",
            class_body, re.MULTILINE
        ):
            methods.append(mm.group(1))
        items.append({
            "type": "class",
            "name": name,
            "bases": bases,
            "docstring": doc[:300] if doc else "",
            "methods": methods,
        })

    # Функции верхнего уровня
    for m in re.finditer(
        r"^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?\s*:[ \t]*\n(?:\s+(?:\"\"\"([\s\S]*?)\"\"\"|\'''([\s\S]*?)\'''))?",
        content, re.MULTILINE
    ):
        name = m.group(1)
        params = m.group(2).strip()
        returns = (m.group(3) or "").strip()
        doc = (m.group(4) or m.group(5) or "").strip()
        items.append({
            "type": "function",
            "name": name,
            "params": params,
            "returns": returns,
            "docstring": doc[:300] if doc else "",
        })

    # Декораторы роутов
    decorators = []
    for m in re.finditer(
        r"^@(\w+)\.(route|get|post|put|delete|patch|api_route|websocket)\s*\(\s*[\"']([^\"']+)[\"'](?:\s*,\s*methods\s*=\s*\[([^\]]+)\])?\)",
        content, re.MULTILINE
    ):
        obj = m.group(1)
        method_type = m.group(2)
        path = m.group(3)
        methods = m.group(4) or method_type.upper()
        # Найти имя функции
        pos = m.end()
        func_m = re.search(r"def\s+(\w+)", content[pos:pos + 300])
        func_name = func_m.group(1) if func_m else "?"
        decorators.append({
            "path": path,
            "methods": methods.replace("'", "").replace('"', ""),
            "handler": func_name,
        })

    return items, decorators


def _find_block_end(content, start):
    """Грубо находит конец блока Python по отступам."""
    lines = content[start:].split("\n")
    if not lines:
        return start
    # Определяем отступ определения
    first_line = lines[0]
    base_indent = len(first_line) - len(first_line.lstrip())
    end = start + len(lines[0]) + 1
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            end += len(line) + 1
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= base_indent and stripped:
            break
        end += len(line) + 1
    return min(end, len(content))


# ═══════════════════════════════════════════════════════════════════════
# АНАЛИЗАТОРЫ: JAVASCRIPT / TYPESCRIPT
# ═══════════════════════════════════════════════════════════════════════

def analyze_js_imports(content):
    """Извлекает import/require."""
    imports = []
    # ES imports
    for m in re.finditer(r"import\s+(?:(?:\{[^}]+\}|\w+|\*\s+as\s+\w+)\s*,?\s*)*\s*from\s*['\"]([^'\"]+)['\"]", content):
        imports.append(m.group(1))
    # require
    for m in re.finditer(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
        imports.append(m.group(1))
    return list(set(imports))


def analyze_js_structure(content, filepath):
    """Извлекает функции, классы, компоненты."""
    items = []

    # Классы
    for m in re.finditer(r"class\s+(\w+)\s*(?:extends\s+(\w+))?\s*\{", content):
        items.append({
            "type": "class",
            "name": m.group(1),
            "extends": m.group(2) or "",
        })

    # Обычные функции
    for m in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", content):
        items.append({
            "type": "function",
            "name": m.group(1),
            "params": m.group(2).strip(),
        })

    # Arrow functions / const
    for m in re.finditer(r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>", content):
        items.append({
            "type": "function",
            "name": m.group(1),
            "params": m.group(2).strip(),
        })

    # React компоненты (PascalCase)
    for m in re.finditer(r"(?:export\s+(?:default\s+)?)?(?:const|function)\s+([A-Z]\w+)", content):
        name = m.group(1)
        if not any(i["name"] == name for i in items):
            items.append({"type": "component", "name": name})

    # Express/Koa/Fastify роуты
    routes = []
    for m in re.finditer(
        r"(?:app|router|server)\.(get|post|put|delete|patch|all|use)\s*\(\s*['\"]([^'\"]+)['\"]",
        content
    ):
        routes.append({"methods": m.group(1).upper(), "path": m.group(2)})

    # Next.js API routes
    if "/api/" in str(filepath) or filepath.endswith((".ts", ".js")):
        for m in re.finditer(r"export\s+(?:default\s+)?(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)", content):
            routes.append({"methods": m.group(1), "path": str(filepath)})

    return items, routes


# ═══════════════════════════════════════════════════════════════════════
# АНАЛИЗАТОРЫ: ОБЩИЕ
# ═══════════════════════════════════════════════════════════════════════

def analyze_html_templates(content, filepath):
    """Анализирует HTML-шаблоны."""
    info = {}

    # Title
    title = re.search(r"<title>([^<]+)</title>", content, re.IGNORECASE)
    if title:
        info["title"] = title.group(1).strip()

    # Template inheritance (Jinja/Django)
    extends = re.search(r"{%\s*extends\s+['\"](.+?)['\"]", content)
    if extends:
        info["extends"] = extends.group(1)

    # Blocks
    blocks = re.findall(r"{%\s*block\s+(\w+)", content)
    if blocks:
        info["blocks"] = list(set(blocks))

    # Forms
    forms = re.findall(r"<form[^>]*action=['\"]([^'\"]*)['\"]", content, re.IGNORECASE)
    if forms:
        info["forms"] = list(set(forms))

    # Script sources
    scripts = re.findall(r"<script[^>]*src=['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
    if scripts:
        info["scripts"] = scripts

    # API calls (fetch, axios)
    fetches = re.findall(r"fetch\s*\(\s*[`'\"]([^`'\"]+)[`'\"]", content)
    if fetches:
        info["api_calls"] = list(set(fetches))

    return info


def analyze_sql_file(content, filepath):
    """Извлекает таблицы и основные операции из SQL."""
    tables = []
    for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?", content, re.IGNORECASE):
        tables.append(m.group(1))
    return tables


def analyze_config_file(content, filepath):
    """Извлекает ключевую информацию из конфигов."""
    info = {}
    name = Path(filepath).name

    if name == "package.json":
        try:
            pkg = json.loads(content)
            info["name"] = pkg.get("name", "")
            info["version"] = pkg.get("version", "")
            info["scripts"] = list(pkg.get("scripts", {}).keys())
            deps = list(pkg.get("dependencies", {}).keys())
            dev_deps = list(pkg.get("devDependencies", {}).keys())
            if deps:
                info["dependencies"] = deps
            if dev_deps:
                info["devDependencies"] = dev_deps
        except json.JSONDecodeError:
            pass

    elif name in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        deps = []
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                deps.append(line.split("#")[0].strip())
        info["packages"] = deps

    elif name == "pyproject.toml":
        # Грубый парсинг — достаточно для обзора
        proj_name = re.search(r'name\s*=\s*"([^"]+)"', content)
        if proj_name:
            info["name"] = proj_name.group(1)
        proj_ver = re.search(r'version\s*=\s*"([^"]+)"', content)
        if proj_ver:
            info["version"] = proj_ver.group(1)
        # dependencies
        deps_section = re.search(r"\[(?:project\.)?dependencies\]\s*\n((?:.*\n)*?)(?:\[|$)", content)
        if deps_section:
            info["dependencies_section"] = deps_section.group(1).strip()[:500]

    elif name in ("docker-compose.yml", "docker-compose.yaml"):
        services = re.findall(r"^\s{2}(\w[\w-]*):", content, re.MULTILINE)
        if services:
            info["services"] = services

    elif name == ".env.example" or name == ".env.sample":
        keys = []
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key = line.split("=")[0].strip()
                if key:
                    keys.append(key)
        info["env_vars"] = keys

    return info


def detect_tech_stack(all_files, all_content):
    """Автоматически определяет технологии проекта."""
    stack = set()
    filenames = {f.name for f in all_files}
    all_text = " ".join(all_content.values())

    # Helper: ищем реальные импорты, а не просто упоминания в строках
    def has_import(module):
        patterns = [
            rf"^\s*import\s+{re.escape(module)}\b",
            rf"^\s*from\s+{re.escape(module)}\b",
            rf"require\s*\(\s*['\"]({re.escape(module)})['\"]",
            rf"from\s+['\"]({re.escape(module)})(?:/[^'\"]*)?['\"]",
        ]
        return any(re.search(p, all_text, re.MULTILINE) for p in patterns)

    def has_dep(name):
        for rel, content in all_content.items():
            fname = Path(rel).name
            if fname in DEPENDENCY_FILES:
                if name.lower() in content.lower():
                    return True
        return False

    # Фреймворки Python
    if has_import("flask"):
        stack.add("Flask")
    if has_import("django"):
        stack.add("Django")
    if has_import("fastapi"):
        stack.add("FastAPI")
    if has_import("aiogram"):
        stack.add("aiogram (Telegram Bot)")
    if has_import("celery"):
        stack.add("Celery")
    if has_import("sqlalchemy"):
        stack.add("SQLAlchemy")
    if has_import("alembic"):
        stack.add("Alembic")
    if has_import("pytest"):
        stack.add("pytest")

    # JS фреймворки
    if has_import("react"):
        stack.add("React")
    if has_import("vue"):
        stack.add("Vue.js")
    if has_import("next") or "next.config" in " ".join(str(f) for f in all_files):
        stack.add("Next.js")
    if has_import("express"):
        stack.add("Express.js")
    if has_import("svelte"):
        stack.add("Svelte")
    if has_import("@angular"):
        stack.add("Angular")

    # Базы данных — по импортам или зависимостям
    if has_import("firebase") or has_import("firebase_admin") or has_dep("firebase"):
        stack.add("Firebase")
    if has_import("mongoose") or has_import("mongodb") or has_dep("mongoose"):
        stack.add("MongoDB")
    if has_import("redis") or has_dep("redis"):
        stack.add("Redis")
    if has_import("psycopg") or has_import("psycopg2") or has_dep("psycopg"):
        stack.add("PostgreSQL")
    if has_import("sqlite3") or has_dep("sqlite"):
        stack.add("SQLite")
    if has_import("pymysql") or has_import("mysql") or has_dep("pymysql"):
        stack.add("MySQL")
    if has_import("prisma") or has_dep("prisma"):
        stack.add("Prisma")

    # Инфраструктура
    if "Dockerfile" in filenames:
        stack.add("Docker")
    if "docker-compose.yml" in filenames or "docker-compose.yaml" in filenames:
        stack.add("Docker Compose")
    if any("nginx" in str(f).lower() for f in all_files):
        stack.add("Nginx")

    # CSS — по зависимостям или конфигам
    if has_dep("tailwindcss") or "tailwind.config" in " ".join(str(f) for f in all_files):
        stack.add("Tailwind CSS")
    if has_dep("bootstrap") or has_import("bootstrap"):
        stack.add("Bootstrap")

    # Тестирование
    if has_import("jest") or has_dep("jest"):
        stack.add("Jest")
    if has_import("vitest") or has_dep("vitest"):
        stack.add("Vitest")

    # Auth
    if has_import("jsonwebtoken") or has_import("jwt") or has_dep("jsonwebtoken"):
        stack.add("JWT")
    if has_dep("passport") or has_import("passport"):
        stack.add("OAuth")

    return sorted(stack)


# ═══════════════════════════════════════════════════════════════════════
# АНАЛИЗ TELEGRAM-БОТОВ (aiogram, python-telegram-bot, telebot)
# ═══════════════════════════════════════════════════════════════════════

def analyze_bot_commands(content, filepath):
    """Находит команды бота (мульти-фреймворк)."""
    commands = []
    # aiogram
    for m in re.finditer(r"Command\(?\s*[\"']?(\w+)[\"']?\s*\)?", content):
        commands.append(m.group(1))
    if "CommandStart" in content:
        commands.append("start")
    # python-telegram-bot
    for m in re.finditer(r"CommandHandler\s*\(\s*[\"'](\w+)[\"']", content):
        commands.append(m.group(1))
    # telebot
    for m in re.finditer(r"@\w+\.message_handler\s*\(\s*commands\s*=\s*\[([^\]]+)\]", content):
        for cmd in re.findall(r"[\"'](\w+)[\"']", m.group(1)):
            commands.append(cmd)
    return list(set(commands))


def analyze_bot_callbacks(content, filepath):
    """Находит callback обработчики (мульти-фреймворк)."""
    callbacks = []
    # aiogram F.data
    for m in re.finditer(r"F\.data\s*==\s*[\"'](.+?)[\"']", content):
        callbacks.append(m.group(1))
    for m in re.finditer(r"F\.data\.startswith\s*\(\s*[\"'](.+?)[\"']", content):
        callbacks.append(m.group(1) + "*")
    # python-telegram-bot
    for m in re.finditer(r"CallbackQueryHandler\s*\([^,]+,\s*pattern\s*=\s*[\"']([^\"']+)[\"']", content):
        callbacks.append(m.group(1))
    return list(set(callbacks))


# ═══════════════════════════════════════════════════════════════════════
# АНАЛИЗ Django
# ═══════════════════════════════════════════════════════════════════════

def analyze_django_urls(content, filepath):
    """Извлекает Django URL patterns."""
    urls = []
    for m in re.finditer(r"path\s*\(\s*[\"']([^\"']*)[\"']\s*,\s*([^,)\s]+)", content):
        urls.append({"path": m.group(1), "view": m.group(2)})
    for m in re.finditer(r"re_path\s*\(\s*[\"']([^\"']*)[\"']\s*,\s*([^,)\s]+)", content):
        urls.append({"path": m.group(1), "view": m.group(2)})
    return urls


def analyze_django_models(content, filepath):
    """Извлекает Django модели и их поля."""
    models = []
    for m in re.finditer(r"class\s+(\w+)\s*\(\s*(?:models\.Model|AbstractUser|AbstractBaseUser)[^)]*\)\s*:", content):
        name = m.group(1)
        block_end = _find_block_end(content, m.start())
        block = content[m.start():block_end]
        fields = []
        for fm in re.finditer(r"(\w+)\s*=\s*models\.(\w+Field)\s*\(", block):
            fields.append(f"{fm.group(1)}: {fm.group(2)}")
        models.append({"name": name, "fields": fields})
    return models


# ═══════════════════════════════════════════════════════════════════════
# СБОРКА ОТЧЁТА
# ═══════════════════════════════════════════════════════════════════════

def analyze_project(root_dir):
    """Главная функция анализа."""
    root = Path(root_dir).resolve()
    files = collect_files(root)

    # Читаем содержимое файлов
    file_contents = {}
    for fpath in files:
        if fpath.stat().st_size > MAX_FILE_SIZE:
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
            rel = str(fpath.relative_to(root))
            file_contents[rel] = content
        except Exception:
            continue

    report = []

    # ─── Шапка ───
    project_name = root.name
    report.append("=" * 70)
    report.append(f"АНАЛИЗ ПРОЕКТА: {project_name.upper()}")
    report.append(f"Путь: {root}")
    report.append(f"Дата анализа: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"Всего файлов: {len(files)}")
    report.append("=" * 70)

    # ─── Технологический стек ───
    stack = detect_tech_stack(files, file_contents)
    report.append("\n\n🔧 ТЕХНОЛОГИЧЕСКИЙ СТЕК")
    report.append("-" * 40)
    if stack:
        report.append("  " + ", ".join(stack))
    else:
        report.append("  Не удалось определить автоматически")

    # ─── Дерево файлов ───
    report.append("\n\n📁 СТРУКТУРА ПРОЕКТА")
    report.append("-" * 40)
    file_stats = defaultdict(int)
    for f in files:
        rel = f.relative_to(root)
        lang = get_file_language(f)
        file_stats[lang] += 1
        size = f.stat().st_size
        size_str = f"{size:,} B" if size < 1024 else f"{size / 1024:.1f} KB"
        report.append(f"  {rel}  ({size_str})")

    # Статистика по языкам
    report.append(f"\n  --- Статистика ---")
    for lang, count in sorted(file_stats.items(), key=lambda x: -x[1]):
        report.append(f"  {lang}: {count} файл(ов)")

    # ─── Зависимости ───
    report.append("\n\n📦 ЗАВИСИМОСТИ")
    report.append("-" * 40)
    found_deps = False
    for rel, content in file_contents.items():
        fname = Path(rel).name
        if fname in DEPENDENCY_FILES and fname not in SKIP_FILES:
            info = analyze_config_file(content, rel)
            if info:
                found_deps = True
                report.append(f"\n  📄 {rel}")
                for key, val in info.items():
                    if isinstance(val, list):
                        report.append(f"     {key}:")
                        for item in val:
                            report.append(f"       - {item}")
                    else:
                        report.append(f"     {key}: {val}")
    if not found_deps:
        report.append("  Файлы зависимостей не найдены")

    # ─── Конфиги (Docker, env, etc.) ───
    report.append("\n\n⚙️  КОНФИГУРАЦИЯ")
    report.append("-" * 40)
    config_found = False
    for rel, content in file_contents.items():
        fname = Path(rel).name
        if fname in ("docker-compose.yml", "docker-compose.yaml", ".env.example", ".env.sample", "Makefile", "Procfile"):
            info = analyze_config_file(content, rel)
            if info:
                config_found = True
                report.append(f"\n  📄 {rel}")
                for key, val in info.items():
                    if isinstance(val, list):
                        report.append(f"     {key}: {', '.join(val)}")
                    else:
                        report.append(f"     {key}: {val}")
    if not config_found:
        report.append("  Конфигурационные файлы не найдены")

    # ─── Python: классы и функции ───
    py_routes = []
    py_django_urls = []
    py_django_models = []
    py_bot_commands = []
    py_bot_callbacks = []
    py_structure = {}

    for rel, content in file_contents.items():
        if not rel.endswith(".py"):
            continue
        items, routes = analyze_python_structure(content, rel)
        if items:
            py_structure[rel] = items
        py_routes.extend([{**r, "file": rel} for r in routes])

        # Django
        django_urls = analyze_django_urls(content, rel)
        if django_urls:
            py_django_urls.extend([{**u, "file": rel} for u in django_urls])
        django_models = analyze_django_models(content, rel)
        if django_models:
            py_django_models.extend([{**m, "file": rel} for m in django_models])

        # Bot — только если файл импортирует бот-фреймворк (реальный import, а не упоминание в строке)
        bot_import_re = r"^\s*(?:from|import)\s+(?:aiogram|telegram|telebot|pyrogram)\b"
        is_bot_file = bool(re.search(bot_import_re, content, re.MULTILINE))
        if is_bot_file:
            cmds = analyze_bot_commands(content, rel)
            if cmds:
                py_bot_commands.extend([(c, rel) for c in cmds])
            cbs = analyze_bot_callbacks(content, rel)
            if cbs:
                py_bot_callbacks.extend([(c, rel) for c in cbs])

    if py_structure:
        report.append("\n\n🐍 PYTHON: КЛАССЫ И ФУНКЦИИ")
        report.append("-" * 40)
        for rel in sorted(py_structure.keys()):
            report.append(f"\n  📄 {rel}")
            for item in py_structure[rel]:
                if item["type"] == "class":
                    bases = f"({item['bases']})" if item.get("bases") else ""
                    report.append(f"     class {item['name']}{bases}")
                    if item.get("docstring"):
                        report.append(f"       \"\"\"{item['docstring']}\"\"\"")
                    if item.get("methods"):
                        report.append(f"       методы: {', '.join(item['methods'])}")
                elif item["type"] == "function":
                    ret = f" -> {item['returns']}" if item.get("returns") else ""
                    report.append(f"     def {item['name']}({item['params']}){ret}")
                    if item.get("docstring"):
                        report.append(f"       \"\"\"{item['docstring']}\"\"\"")

    # ─── Роуты (Flask/FastAPI/Django) ───
    all_routes = py_routes + py_django_urls
    if all_routes:
        report.append("\n\n🌐 РОУТЫ / ЭНДПОИНТЫ (Python)")
        report.append("-" * 40)
        for r in all_routes:
            if "methods" in r:
                report.append(f"  [{r['methods']}] {r['path']}  →  {r.get('handler', r.get('view', '?'))}()  ({r['file']})")
            else:
                report.append(f"  {r['path']}  →  {r.get('view', '?')}  ({r['file']})")

    # ─── Django модели ───
    if py_django_models:
        report.append("\n\n🗃️  DJANGO МОДЕЛИ")
        report.append("-" * 40)
        for model in py_django_models:
            report.append(f"\n  {model['name']}  ({model['file']})")
            for field in model.get("fields", []):
                report.append(f"     {field}")

    # ─── Telegram-бот ───
    if py_bot_commands or py_bot_callbacks:
        report.append("\n\n🤖 TELEGRAM-БОТ")
        report.append("-" * 40)
        if py_bot_commands:
            report.append("  Команды:")
            for cmd, f in py_bot_commands:
                report.append(f"    /{cmd}  ({f})")
        if py_bot_callbacks:
            report.append("  Callback-кнопки:")
            for cb, f in py_bot_callbacks:
                report.append(f"    {cb}  ({f})")

    # ─── JavaScript/TypeScript ───
    js_structure = {}
    js_routes = []

    for rel, content in file_contents.items():
        if not any(rel.endswith(ext) for ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte")):
            continue
        items, routes = analyze_js_structure(content, rel)
        if items:
            js_structure[rel] = items
        js_routes.extend([{**r, "file": rel} for r in routes])

    if js_structure:
        report.append("\n\n📜 JAVASCRIPT/TYPESCRIPT: СТРУКТУРА")
        report.append("-" * 40)
        for rel in sorted(js_structure.keys()):
            report.append(f"\n  📄 {rel}")
            for item in js_structure[rel]:
                if item["type"] == "class":
                    ext = f" extends {item['extends']}" if item.get("extends") else ""
                    report.append(f"     class {item['name']}{ext}")
                elif item["type"] == "component":
                    report.append(f"     component {item['name']}")
                elif item["type"] == "function":
                    report.append(f"     function {item['name']}({item.get('params', '')})")

    if js_routes:
        report.append("\n\n🌐 РОУТЫ / ЭНДПОИНТЫ (JS)")
        report.append("-" * 40)
        for r in js_routes:
            report.append(f"  [{r['methods']}] {r['path']}  ({r['file']})")

    # ─── HTML шаблоны ───
    templates = {}
    for rel, content in file_contents.items():
        if any(rel.endswith(ext) for ext in (".html", ".htm", ".jinja", ".jinja2", ".ejs", ".hbs")):
            info = analyze_html_templates(content, rel)
            if info:
                templates[rel] = info

    if templates:
        report.append("\n\n📄 HTML-ШАБЛОНЫ")
        report.append("-" * 40)
        for rel, info in sorted(templates.items()):
            report.append(f"\n  📄 {rel}")
            for key, val in info.items():
                if isinstance(val, list):
                    report.append(f"     {key}: {', '.join(val)}")
                else:
                    report.append(f"     {key}: {val}")

    # ─── SQL ───
    sql_tables = []
    for rel, content in file_contents.items():
        if rel.endswith(".sql"):
            tables = analyze_sql_file(content, rel)
            if tables:
                sql_tables.extend([(t, rel) for t in tables])

    if sql_tables:
        report.append("\n\n🗄️  SQL ТАБЛИЦЫ")
        report.append("-" * 40)
        for table, f in sql_tables:
            report.append(f"  {table}  ({f})")

    # ─── API вызовы из фронтенда ───
    api_calls = []
    for rel, content in file_contents.items():
        if any(rel.endswith(ext) for ext in (".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".html")):
            fetches = re.findall(r"fetch\s*\(\s*[`'\"](/?[^`'\"]+)[`'\"]", content)
            axios_calls = re.findall(r"axios\.(?:get|post|put|delete|patch)\s*\(\s*[`'\"](/?[^`'\"]+)[`'\"]", content)
            for url in fetches + axios_calls:
                api_calls.append((url, rel))

    if api_calls:
        report.append("\n\n🔗 API-ВЫЗОВЫ ИЗ ФРОНТЕНДА")
        report.append("-" * 40)
        seen = set()
        for url, f in api_calls:
            key = f"{url} ({f})"
            if key not in seen:
                seen.add(key)
                report.append(f"  {url}  ← {f}")

    # ─── TODO / FIXME / HACK ───
    todos = []
    todo_tags = ("TODO", "FIXME", "HACK", "XXX", "BUG")
    todo_pattern = re.compile(r"(?:#|//|/\*|\*)\s*(?:TODO|FIXME|HACK|XXX|BUG)\b")
    for rel, content in file_contents.items():
        for i, line in enumerate(content.splitlines(), 1):
            m = todo_pattern.search(line)
            if m:
                stripped = line.strip()
                # Пропускаем, если строка — определение самого паттерна
                if "todo_pattern" in stripped or "todo_tags" in stripped:
                    continue
                if len(stripped) > 200:
                    stripped = stripped[:200] + "..."
                # Определяем тег
                for tag in todo_tags:
                    if tag in line[m.start():]:
                        todos.append((tag, rel, i, stripped))
                        break

    if todos:
        report.append("\n\n📌 TODO / FIXME / HACK")
        report.append("-" * 40)
        for tag, f, line_no, text in todos[:100]:  # макс 100
            report.append(f"  [{tag}] {f}:{line_no}")
            report.append(f"    {text}")

    # ─── Конец ───
    report.append("\n\n" + "=" * 70)
    report.append("КОНЕЦ АНАЛИЗА")
    report.append("=" * 70)

    return "\n".join(report)


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    project_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    to_stdout = "--stdout" in sys.argv

    if not os.path.isdir(project_dir):
        print(f"Ошибка: '{project_dir}' не является директорией")
        sys.exit(1)

    print(f"🔍 Анализирую проект: {Path(project_dir).resolve()}")
    result = analyze_project(project_dir)

    if to_stdout:
        print(result)
    else:
        output_file = os.path.join(project_dir, "project_analysis.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"\n✅ Готово! Результат: {output_file}")
        print(f"   Размер: {os.path.getsize(output_file):,} bytes")
        print(f"\n💡 Скопируй содержимое файла и передай в чат с Claude для анализа.")
