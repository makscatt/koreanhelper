from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from functools import wraps
import os
import hmac
import hashlib
import json
import requests as http_requests  # ← ДОБАВЛЕНО: для запросов к kimchi-серверу
import base64

# ── Google Cloud TTS (через API Key — без библиотеки) ──
GOOGLE_TTS_API_KEY = os.environ.get('GOOGLE_TTS_API_KEY', '')
TTS_ENABLED = bool(GOOGLE_TTS_API_KEY)
if TTS_ENABLED:
    print("✅ Google Cloud TTS подключён (API Key)")
else:
    print("⚠️  Google Cloud TTS: нет GOOGLE_TTS_API_KEY")

TTS_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tts_cache')
os.makedirs(TTS_CACHE_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///korean_learning.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ── ДОБАВЛЕНО: URL kimchi-сервера ──
KIMCHI_API_URL = os.environ.get('KIMCHI_API_URL', 'https://kimchi-server.onrender.com')
KIMCHI_BOT_TOKEN = os.environ.get('KIMCHI_BOT_TOKEN', '')

# ── OpenAI для Word Hub ──
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = 'gpt-5.1'


# ══════════════════════════════════════════
#  МОДЕЛИ
# ══════════════════════════════════════════

class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=True)
    telegram_id = db.Column(db.String(50), nullable=True, unique=True)  # для ТГ-юзеров

class StudentAccount(db.Model):
    """Логин/пароль для ученика — создаётся учителем"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    password_plain = db.Column(db.String(200), nullable=False, default="")
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student', backref=db.backref('account', uselist=False))

class Note(db.Model):
    """Заметки учителя по ученику (архив)"""
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(50), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ModuleProgress(db.Model):
    """Прогресс ученика по каждому модулю-тренажёру"""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    module = db.Column(db.String(50), nullable=False)
    exercises_done = db.Column(db.Integer, default=0)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('student_id', 'module', name='uq_student_module'),
    )

class SessionLog(db.Model):
    """Лог каждого посещения тренажёра"""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    module = db.Column(db.String(50), nullable=False)
    exercises_done = db.Column(db.Integer, default=0)
    duration_sec = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)

class SectionCheck(db.Model):
    """Чекбоксы секций тренажёров (например 'phrases:start' = пройдено)"""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    trainer = db.Column(db.String(50), nullable=False)   # например 'phrases'
    section = db.Column(db.String(100), nullable=False)   # например 'start'
    checked = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('student_id', 'trainer', 'section', name='uq_section_check'),
    )

class TrainerItemProgress(db.Model):
    """Прогресс по отдельным элементам тренажёра (знаю/не знаю фразу и т.д.)"""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    trainer = db.Column(db.String(50), nullable=False)    # например 'phrases'
    item_id = db.Column(db.String(200), nullable=False)   # id элемента из JSON
    status = db.Column(db.Text, nullable=False)          # 'know' / 'done' / HTML highlights
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('student_id', 'trainer', 'item_id', name='uq_item_progress'),
    )

class WordHub(db.Model):
    """Персональный словарь ученика — слова добавляются через ИИ-анализ"""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    word_kor = db.Column(db.String(100), nullable=False)      # словарная форма
    word_rus = db.Column(db.String(200), nullable=False)      # перевод
    original_form = db.Column(db.String(100), nullable=False)  # как было выделено
    part_of_speech = db.Column(db.String(50), default='')      # 동사, 명사 и т.д.
    is_learned = db.Column(db.Boolean, default=False)
    added_by = db.Column(db.String(20), default='teacher')     # 'teacher' или 'student'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('student_id', 'word_kor', name='uq_student_word'),
    )


# ══════════════════════════════════════════
#  ДЕКОРАТОРЫ ДОСТУПА
# ══════════════════════════════════════════

def teacher_required(f):
    """Маршрут доступен только учителю"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'teacher':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def student_required(f):
    """Маршрут доступен только ученику"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'student':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def login_required(f):
    """Маршрут доступен любому авторизованному пользователю"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'role' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── ДОБАВЛЕНО: декоратор для участников группы ──
def group_required(f):
    """Маршрут доступен только участнику закрытой группы"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'group_member':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def _owns_student(student_id):
    """Проверяет, что текущий учитель владеет этим учеником"""
    student = Student.query.get_or_404(student_id)
    if student.teacher_id != session.get('teacher_id'):
        return None
    return student


# ══════════════════════════════════════════
#  АВТОРИЗАЦИЯ (общая — учитель и ученик)
# ══════════════════════════════════════════

@app.route('/')
def index():
    if session.get('role') == 'teacher':
        return redirect(url_for('select_student'))
    if session.get('role') == 'student':
        return redirect(url_for('student_dashboard'))
    # ── ДОБАВЛЕНО: редирект для участника группы ──
    if session.get('role') == 'group_member':
        return redirect(url_for('group_trainers'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        login_as = request.form.get('login_as', 'teacher')

        if login_as == 'teacher':
            teacher = Teacher.query.filter_by(username=username).first()
            if teacher and check_password_hash(teacher.password_hash, password):
                session.clear()
                session['role'] = 'teacher'
                session['teacher_id'] = teacher.id
                session['teacher_name'] = teacher.username
                return redirect(url_for('select_student'))
            else:
                flash('Неверный логин или пароль', 'error')

        elif login_as == 'student':
            account = StudentAccount.query.filter_by(username=username).first()
            if account and check_password_hash(account.password_hash, password):
                if not account.is_active:
                    flash('Аккаунт заблокирован. Обратитесь к учителю.', 'error')
                else:
                    session.clear()
                    session['role'] = 'student'
                    session['student_account_id'] = account.id
                    session['student_id'] = account.student_id
                    session['student_name'] = account.student.name
                    return redirect(url_for('student_dashboard'))
            else:
                flash('Неверный логин или пароль', 'error')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация учителей — только учителя регистрируются сами"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if Teacher.query.filter_by(username=username).first():
            flash('Пользователь уже существует', 'error')
        else:
            teacher = Teacher(
                username=username,
                password_hash=generate_password_hash(password)
            )
            db.session.add(teacher)
            db.session.commit()
            flash('Регистрация успешна! Войдите в систему', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ══════════════════════════════════════════
#  ПУТЬ 3: ДОСТУП ДЛЯ УЧАСТНИКОВ ГРУППЫ
#  (через Telegram Web App)
# ══════════════════════════════════════════

def _verify_telegram_webapp(init_data):
    """Проверяет подпись initData от Telegram Web App."""
    if not init_data or not KIMCHI_BOT_TOKEN:
        return {}
    try:
        from urllib.parse import parse_qs
        parsed = parse_qs(init_data)
        received_hash = parsed.get('hash', [''])[0]
        if not received_hash:
            return {}
        pairs = []
        for key, values in parsed.items():
            if key != 'hash':
                pairs.append(f'{key}={values[0]}')
        pairs.sort()
        data_check_string = '\n'.join(pairs)
        secret_key = hmac.new(b'WebAppData', KIMCHI_BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash != received_hash:
            return {}
        user_json = parsed.get('user', [''])[0]
        if user_json:
            return json.loads(user_json)
        return {}
    except Exception:
        return {}


@app.route('/group/webapp')
def group_webapp():
    """Открывается как Telegram Web App. Проверяет initData и редиректит."""
    # Если уже авторизован — сразу на тренажёры
    if session.get('role') == 'group_member':
        return redirect(url_for('group_trainers'))

    return '''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { display:flex; justify-content:center; align-items:center;
               height:100vh; margin:0; font-family:sans-serif; background:#f5f5f5; }
        .error { color:#c00; text-align:center; padding:20px; }
    </style>
</head>
<body>
    <div id="status">Загрузка...</div>
    <script>
        var tg = window.Telegram.WebApp;
        tg.ready();
        tg.requestFullscreen();
        tg.expand();
        var initData = tg.initData;
        if (!initData) {
            document.getElementById('status').innerHTML =
                '<div class="error">Откройте через Telegram-бота</div>';
        } else {
            fetch('/group/webapp/verify', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({init_data: initData})
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok) {
                    window.location.replace('/group/trainers');
                } else {
                    document.getElementById('status').innerHTML =
                        '<div class="error">' + (data.error || 'Нет доступа') + '</div>';
                }
            })
            .catch(function() {
                document.getElementById('status').innerHTML =
                    '<div class="error">Ошибка связи</div>';
            });
        }
    </script>
</body>
</html>'''


@app.route('/group/webapp/verify', methods=['POST'])
def group_webapp_verify():
    """Проверяет initData и создаёт сессию group_member с реальным Student."""
    data = request.get_json() or {}
    init_data = data.get('init_data', '')

    user = _verify_telegram_webapp(init_data)
    if not user or not user.get('id'):
        return jsonify({'ok': False, 'error': 'Не удалось проверить данные Telegram'})

    telegram_id = str(user['id'])

    try:
        resp = http_requests.get(
            f'{KIMCHI_API_URL}/load/{telegram_id}',
            timeout=10
        )
        kimchi_data = resp.json()
    except Exception:
        return jsonify({'ok': False, 'error': 'Ошибка связи с сервером'})

    if not kimchi_data.get('tgmembership') and not kimchi_data.get('promember'):
        return jsonify({'ok': False, 'error': 'Доступно только для участников группы'})

    # Находим или создаём виртуального Student для этого ТГ-юзера
    student = Student.query.filter_by(telegram_id=telegram_id).first()
    if not student:
        tg_name = user.get('first_name', 'TG') + (' ' + user.get('last_name', '')).rstrip()
        student = Student(
            name=tg_name,
            telegram_id=telegram_id,
            teacher_id=None,
        )
        db.session.add(student)
        db.session.commit()

    session.clear()
    session['role'] = 'group_member'
    session['telegram_id'] = telegram_id
    session['student_id'] = student.id
    session['student_name'] = student.name
    return jsonify({'ok': True})


class _GroupStudent:
    """Фейковый student-заглушка — на случай если сессия без student_id."""
    id = 0
    name = 'Группа'

_group_student = _GroupStudent()


def _get_group_student():
    """Возвращает реального Student для group_member или заглушку."""
    sid = session.get('student_id')
    if sid:
        s = Student.query.get(sid)
        if s:
            return s
    return _group_student


@app.route('/group/trainers')
@group_required
def group_trainers():
    """Меню тренажёров для участника группы."""
    student = _get_group_student()
    has_real_student = student.id != 0
    return render_template('trainer_menu.html',
                           student=student, student_mode=True,
                           readonly=not has_real_student,
                           group_mode=True)


@app.route('/group/trainer/<module>')
@group_required
def group_trainer(module):
    """Любой тренажёр для участника группы."""
    template_map = {
        'alphabet':  'trainer_alphabet.html',
        'numbers':   'trainer_numbers.html',
        'time':      'trainer_time.html',
        'money':     'trainer_money.html',
        'dates':     'trainer_dates.html',
        'colors':    'trainer_colors.html',
        'weekdays':  'trainer_weekdays.html',
        'weather':   'trainer_weather.html',
        'locations': 'trainer_locations.html',
        'verbs':     'trainer_verbs.html',
        'sentences': 'trainer_sentences.html',
        'grammar':   'trainer_grammar.html',
        'text':      'trainer_text.html',
        'cards':     'trainer_cards.html',
        'words':     'trainer_words.html',
        'quiz':      'trainer_quiz.html',
        'video':     'trainer_video.html',
        'pictures':  'trainer_pictures.html',
        'phrases':   'trainer_phrases.html',
        'hub':       'trainer_hub.html',
    }
    template = template_map.get(module)
    if not template:
        return redirect(url_for('group_trainers'))
    student = _get_group_student()
    has_real_student = student.id != 0
    return render_template(template,
                           student=student, student_mode=True,
                           readonly=not has_real_student,
                           group_mode=True)


# ══════════════════════════════════════════
#  ИНТЕРФЕЙС УЧИТЕЛЯ
# ══════════════════════════════════════════

@app.route('/students')
@teacher_required
def select_student():
    students = Student.query.filter_by(teacher_id=session['teacher_id']).all()
    return render_template('select_student.html', students=students)

@app.route('/students/add', methods=['POST'])
@teacher_required
def add_student():
    name = request.form.get('name')
    if name:
        student = Student(name=name, teacher_id=session['teacher_id'])
        db.session.add(student)
        db.session.commit()
        flash('Ученик добавлен', 'success')
    return redirect(url_for('select_student'))

@app.route('/students/<int:student_id>/delete', methods=['POST'])
@teacher_required
def delete_student(student_id):
    student = _owns_student(student_id)
    if student:
        if student.account:
            db.session.delete(student.account)
        Note.query.filter_by(student_id=student_id).delete()
        ModuleProgress.query.filter_by(student_id=student_id).delete()
        SessionLog.query.filter_by(student_id=student_id).delete()
        SectionCheck.query.filter_by(student_id=student_id).delete()
        TrainerItemProgress.query.filter_by(student_id=student_id).delete()
        WordHub.query.filter_by(student_id=student_id).delete()
        db.session.delete(student)
        db.session.commit()
        flash('Ученик удалён', 'success')
    return redirect(url_for('select_student'))

@app.route('/students/<int:student_id>/create-account', methods=['POST'])
@teacher_required
def create_student_account(student_id):
    """Учитель создаёт логин/пароль для ученика"""
    student = _owns_student(student_id)
    if not student:
        flash('Нет доступа', 'error')
        return redirect(url_for('select_student'))

    if student.account:
        flash('У этого ученика уже есть аккаунт', 'error')
        return redirect(url_for('select_student'))

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        flash('Заполните логин и пароль', 'error')
        return redirect(url_for('select_student'))

    if StudentAccount.query.filter_by(username=username).first():
        flash(f'Логин «{username}» уже занят', 'error')
        return redirect(url_for('select_student'))

    account = StudentAccount(
        username=username,
        password_hash=generate_password_hash(password),
        password_plain=password,
        student_id=student_id
    )
    db.session.add(account)
    db.session.commit()
    flash(f'Аккаунт создан: логин «{username}»', 'success')
    return redirect(url_for('select_student'))

@app.route('/students/<int:student_id>/toggle-account', methods=['POST'])
@teacher_required
def toggle_student_account(student_id):
    """Блокировка/разблокировка аккаунта ученика"""
    student = _owns_student(student_id)
    if student and student.account:
        student.account.is_active = not student.account.is_active
        db.session.commit()
        status = 'разблокирован' if student.account.is_active else 'заблокирован'
        flash(f'Аккаунт {status}', 'success')
    return redirect(url_for('select_student'))

@app.route('/students/<int:student_id>/delete-account', methods=['POST'])
@teacher_required
def delete_student_account(student_id):
    """Удалить аккаунт ученика (ученик останется, просто без логина)"""
    student = _owns_student(student_id)
    if student and student.account:
        db.session.delete(student.account)
        db.session.commit()
        flash('Аккаунт удалён', 'success')
    return redirect(url_for('select_student'))

@app.route('/dashboard/<int:student_id>')
@teacher_required
def dashboard(student_id):
    student = _owns_student(student_id)
    if not student:
        return redirect(url_for('select_student'))

    session['current_student_id'] = student_id
    session['current_student_name'] = student.name

    progress_rows = ModuleProgress.query.filter_by(student_id=student_id).all()
    total_exercises = sum(p.exercises_done for p in progress_rows)
    active_modules = len(progress_rows)

    last_session = SessionLog.query.filter_by(student_id=student_id)\
        .order_by(SessionLog.started_at.desc()).first()
    last_active = last_session.started_at.strftime('%d.%m %H:%M') if last_session else '—'

    homework_items = TrainerItemProgress.query.filter_by(
        student_id=student_id, status='homework'
    ).all()

    return render_template('dashboard.html',
        student=student,
        total_exercises=total_exercises,
        active_modules=active_modules,
        last_active=last_active,
        homework_items=homework_items
    )


# ══════════════════════════════════════════
#  ИНТЕРФЕЙС УЧЕНИКА
# ══════════════════════════════════════════

@app.route('/my/trainers')
@student_required
def student_trainers():
    """Главная страница ученика — меню тренажёров"""
    student = Student.query.get(session['student_id'])
    return render_template('trainer_menu.html', student=student, student_mode=True)

@app.route('/my/dashboard')
@student_required
def student_dashboard():
    """Дашборд ученика"""
    student = Student.query.get(session['student_id'])

    progress_rows = ModuleProgress.query.filter_by(student_id=student.id).all()
    total_exercises = sum(p.exercises_done for p in progress_rows)
    active_modules = len(progress_rows)

    last_session = SessionLog.query.filter_by(student_id=student.id)\
        .order_by(SessionLog.started_at.desc()).first()
    last_active = last_session.started_at.strftime('%d.%m %H:%M') if last_session else '—'

    homework_items = TrainerItemProgress.query.filter_by(
        student_id=student.id, status='homework'
    ).all()

    return render_template('dashboard.html',
        student=student,
        total_exercises=total_exercises,
        active_modules=active_modules,
        last_active=last_active,
        homework_items=homework_items,
        student_mode=True
    )

@app.route('/my/trainer/<module>')
@student_required
def student_trainer(module):
    """Универсальный маршрут для ученика — любой тренажёр по имени"""
    student = Student.query.get(session['student_id'])
    template_map = {
        'alphabet':  'trainer_alphabet.html',
        'numbers':   'trainer_numbers.html',
        'time':      'trainer_time.html',
        'money':     'trainer_money.html',
        'dates':     'trainer_dates.html',
        'colors':    'trainer_colors.html',
        'weekdays':  'trainer_weekdays.html',
        'weather':   'trainer_weather.html',
        'locations': 'trainer_locations.html',
        'verbs':     'trainer_verbs.html',
        'sentences': 'trainer_sentences.html',
        'grammar':   'trainer_grammar.html',
        'text':      'trainer_text.html',
        'cards':     'trainer_cards.html',
        'words':     'trainer_words.html',
        'quiz':      'trainer_quiz.html',
        'video':     'trainer_video.html',
        'pictures':  'trainer_pictures.html',
        'phrases':   'trainer_phrases.html',
        'hub':       'trainer_hub.html',
    }
    template = template_map.get(module)
    if not template:
        return redirect(url_for('student_trainers'))
    return render_template(template, student=student, student_mode=True)

@app.route('/my/history')
@student_required
def student_history():
    """Ученик смотрит свои заметки (только чтение)"""
    student = Student.query.get(session['student_id'])
    return render_template('history.html', student=student, student_mode=True)


# ══════════════════════════════════════════
#  PROGRESS API  (работает для обоих ролей)
# ══════════════════════════════════════════

def _get_student_id_from_request(data):
    """Определяет student_id в зависимости от роли"""
    role = session.get('role')
    if role == 'student':
        return session.get('student_id')
    if role == 'group_member':
        return session.get('student_id')  # реальный Student, созданный при верификации
    return data.get('student_id')  # учитель передаёт явно

@app.route('/api/progress/ping', methods=['POST'])
@login_required
def progress_ping():
    """Вызывается при входе в тренажёр — логирует начало сессии"""
    # group_member без реального student_id — пропускаем
    if session.get('role') == 'group_member' and not session.get('student_id'):
        return jsonify({'ok': True, 'session_id': None})

    data = request.get_json()
    student_id = _get_student_id_from_request(data)
    module = data.get('module')

    if not student_id or not module:
        return jsonify({'ok': False}), 400

    log = SessionLog(student_id=student_id, module=module)
    db.session.add(log)
    db.session.commit()
    return jsonify({'ok': True, 'session_id': log.id})

@app.route('/api/progress/update', methods=['POST'])
@login_required
def progress_update():
    """Вызывается при каждом выполненном упражнении"""
    # group_member без реального student_id — пропускаем
    if session.get('role') == 'group_member' and not session.get('student_id'):
        return jsonify({'ok': True, 'total': 0})

    data = request.get_json()
    student_id = _get_student_id_from_request(data)
    module = data.get('module')
    session_id = data.get('session_id')
    duration_sec = data.get('duration_sec', 0)

    if not student_id or not module:
        return jsonify({'ok': False}), 400

    prog = ModuleProgress.query.filter_by(
        student_id=student_id, module=module
    ).first()

    if prog:
        prog.exercises_done += 1
        prog.last_active = datetime.utcnow()
    else:
        prog = ModuleProgress(student_id=student_id, module=module, exercises_done=1)
        db.session.add(prog)

    if session_id:
        log = SessionLog.query.get(session_id)
        if log:
            log.exercises_done += 1
            log.duration_sec = duration_sec

    db.session.commit()
    return jsonify({'ok': True, 'total': prog.exercises_done})


# ══════════════════════════════════════════
#  NOTES API  (заметки — из localStorage в БД)
# ══════════════════════════════════════════

@app.route('/api/notes/list', methods=['POST'])
@login_required
def notes_list():
    """Получить все заметки ученика"""
    data = request.get_json() or {}
    student_id = _get_student_id_from_request(data)
    if not student_id:
        return jsonify({'ok': False}), 400

    notes = Note.query.filter_by(student_id=student_id)\
        .order_by(Note.created_at.desc()).all()
    return jsonify({'ok': True, 'notes': [
        {'id': n.id, 'text': n.text, 'date': n.date}
        for n in notes
    ]})

@app.route('/api/notes/save', methods=['POST'])
@login_required
def notes_save():
    """Сохранить заметку в архив (только учитель)"""
    if session.get('role') != 'teacher':
        return jsonify({'ok': False, 'error': 'readonly'}), 403

    data = request.get_json()
    student_id = data.get('student_id')
    text = data.get('text', '').strip()
    date_str = data.get('date', '')

    if not student_id or not text:
        return jsonify({'ok': False}), 400

    # Проверяем — если есть заметка за сегодня, дописываем к ней
    today = datetime.utcnow().strftime('%d.%m.%Y')
    existing = Note.query.filter_by(student_id=student_id)\
        .filter(Note.date.like(f'{today}%'))\
        .order_by(Note.created_at.desc()).first()

    if existing:
        existing.text += '\n\n_____\n\n' + text
        existing.date = date_str
    else:
        note = Note(text=text, date=date_str, student_id=student_id)
        db.session.add(note)

    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/notes/delete', methods=['POST'])
@login_required
def notes_delete():
    """Удалить заметку (только учитель)"""
    if session.get('role') != 'teacher':
        return jsonify({'ok': False, 'error': 'readonly'}), 403

    data = request.get_json()
    note_id = data.get('note_id')
    if not note_id:
        return jsonify({'ok': False}), 400

    Note.query.filter_by(id=note_id).delete()
    db.session.commit()
    return jsonify({'ok': True})


# ══════════════════════════════════════════
#  SECTION CHECKS API  (чекбоксы секций)
# ══════════════════════════════════════════

@app.route('/api/sections/get', methods=['POST'])
@login_required
def sections_get():
    """Получить состояние чекбоксов секций для тренажёра"""
    data = request.get_json() or {}
    student_id = _get_student_id_from_request(data)
    trainer = data.get('trainer', '')
    if not student_id or not trainer:
        return jsonify({'ok': False}), 400

    checks = SectionCheck.query.filter_by(
        student_id=student_id, trainer=trainer
    ).all()
    result = {c.section: c.checked for c in checks}
    return jsonify({'ok': True, 'sections': result})

@app.route('/api/sections/toggle', methods=['POST'])
@login_required
def sections_toggle():
    """Переключить чекбокс секции (только учитель)"""
    if session.get('role') != 'teacher':
        return jsonify({'ok': False, 'error': 'readonly'}), 403

    data = request.get_json()
    student_id = data.get('student_id')
    trainer = data.get('trainer', '')
    section = data.get('section', '')
    if not student_id or not trainer or not section:
        return jsonify({'ok': False}), 400

    check = SectionCheck.query.filter_by(
        student_id=student_id, trainer=trainer, section=section
    ).first()

    if check:
        check.checked = not check.checked
        check.updated_at = datetime.utcnow()
    else:
        check = SectionCheck(
            student_id=student_id, trainer=trainer,
            section=section, checked=True
        )
        db.session.add(check)

    db.session.commit()
    return jsonify({'ok': True, 'checked': check.checked})


# ══════════════════════════════════════════
#  TRAINER ITEM PROGRESS API  (знаю/не знаю)
# ══════════════════════════════════════════

@app.route('/api/items/get', methods=['POST'])
@login_required
def items_get():
    """Получить прогресс по элементам тренажёра"""
    data = request.get_json() or {}
    student_id = _get_student_id_from_request(data)
    trainer = data.get('trainer', '')
    if not student_id or not trainer:
        return jsonify({'ok': False}), 400

    items = TrainerItemProgress.query.filter_by(
        student_id=student_id, trainer=trainer
    ).all()
    result = {i.item_id: i.status for i in items}
    return jsonify({'ok': True, 'items': result})

@app.route('/api/items/set', methods=['POST'])
@login_required
def items_set():
    """Установить статус элемента (только учитель)"""
    if session.get('role') != 'teacher':
        return jsonify({'ok': False, 'error': 'readonly'}), 403

    data = request.get_json()
    student_id = data.get('student_id')
    trainer = data.get('trainer', '')
    item_id = data.get('item_id', '')
    status = data.get('status', '')  # 'know' или пустая строка для удаления
    if not student_id or not trainer or not item_id:
        return jsonify({'ok': False}), 400

    existing = TrainerItemProgress.query.filter_by(
        student_id=student_id, trainer=trainer, item_id=item_id
    ).first()

    if not status:
        # Удаляем (не знаю)
        if existing:
            db.session.delete(existing)
    else:
        if existing:
            existing.status = status
            existing.updated_at = datetime.utcnow()
        else:
            existing = TrainerItemProgress(
                student_id=student_id, trainer=trainer,
                item_id=item_id, status=status
            )
            db.session.add(existing)

    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/highlights/save', methods=['POST'])
@login_required
def highlights_save():
    """Сохранить выделения (маркеры) — доступно и учителю и ученику"""
    data = request.get_json() or {}
    student_id = _get_student_id_from_request(data)
    trainer = data.get('trainer', '')
    item_id = data.get('item_id', '')
    html = data.get('html', '')
    if not student_id or not trainer or not item_id:
        return jsonify({'ok': False}), 400

    # Store highlights with "hl:" prefix to separate from status items
    hl_key = f'hl:{item_id}'
    existing = TrainerItemProgress.query.filter_by(
        student_id=student_id, trainer=trainer, item_id=hl_key
    ).first()

    if not html:
        if existing:
            db.session.delete(existing)
    else:
        if existing:
            existing.status = html
            existing.updated_at = datetime.utcnow()
        else:
            existing = TrainerItemProgress(
                student_id=student_id, trainer=trainer,
                item_id=hl_key, status=html
            )
            db.session.add(existing)

    db.session.commit()
    return jsonify({'ok': True})


# ══════════════════════════════════════════
#  WORD HUB API  (персональный словарь с ИИ)
# ══════════════════════════════════════════

def _analyze_korean_word(text):
    """Отправляет слово в OpenAI для анализа: словарная форма + перевод + часть речи.
    Принимает как корейские, так и русские слова."""
    if not OPENAI_API_KEY:
        return None
    try:
        resp = http_requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': OPENAI_MODEL,
                'reasoning_effort': 'none',
                'max_completion_tokens': 200,
                'messages': [
                    {'role': 'system', 'content': (
                        'Ты — помощник для изучения корейского языка. '
                        'Пользователь пришлёт слово — оно может быть на корейском (возможно в спрягаемой форме) ИЛИ на русском. '
                        'Твоя задача — всегда вернуть пару корейское↔русское. '
                        'Если слово на корейском: приведи к словарной форме, переведи на русский. '
                        'Если слово на русском: переведи на корейский (словарная форма). '
                        'Верни ТОЛЬКО JSON без обёрток: '
                        '{"base":"словарная форма на корейском","rus":"перевод на русский (краткий)","pos":"часть речи на русском"} '
                        'Если не можешь определить — верни {"base":"","rus":"","pos":""}.'
                    )},
                    {'role': 'user', 'content': text.strip()}
                ],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"OpenAI error: {resp.status_code} {resp.text[:200]}")
            return None
        content = resp.json()['choices'][0]['message']['content']
        # Чистим от возможных markdown-обёрток
        content = content.strip()
        if content.startswith('```'):
            content = content.split('\n', 1)[-1].rsplit('```', 1)[0]
        return json.loads(content)
    except Exception as e:
        print(f"OpenAI analyze error: {e}")
        return None


def _analyze_korean_batch(words_list):
    """Отправляет список слов (корейских и/или русских) в OpenAI одним запросом.
    Возвращает список dict: [{"base":"...", "rus":"...", "pos":"..."}, ...]"""
    if not OPENAI_API_KEY or not words_list:
        return None
    try:
        numbered = '\n'.join(f'{i+1}. {w}' for i, w in enumerate(words_list))
        resp = http_requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': OPENAI_MODEL,
                'reasoning_effort': 'low',
                'max_completion_tokens': 3000,
                'messages': [
                    {'role': 'system', 'content': (
                        'Ты — помощник для изучения корейского языка. '
                        'Пользователь пришлёт нумерованный список слов — каждое может быть на корейском (возможно спрягаемое) ИЛИ на русском. '
                        'Для КАЖДОГО слова верни пару корейское↔русское. '
                        'Если слово на корейском: приведи к словарной форме, переведи на русский. '
                        'Если слово на русском: переведи на корейский (словарная форма). '
                        'Верни ТОЛЬКО JSON-массив без обёрток, ровно столько элементов сколько слов в списке: '
                        '[{"base":"словарная форма на корейском","rus":"перевод на русский (краткий)","pos":"часть речи на русском"}, ...] '
                        'Если какое-то слово не удалось определить — верни для него {"base":"","rus":"","pos":""}. '
                        'Порядок элементов должен точно соответствовать порядку слов во входном списке.'
                    )},
                    {'role': 'user', 'content': numbered}
                ],
            },
            timeout=45,
        )
        if resp.status_code != 200:
            print(f"OpenAI batch error: {resp.status_code} {resp.text[:300]}")
            return None
        content = resp.json()['choices'][0]['message']['content']
        content = content.strip()
        if content.startswith('```'):
            content = content.split('\n', 1)[-1].rsplit('```', 1)[0]
        result = json.loads(content)
        if isinstance(result, list):
            return result
        return None
    except Exception as e:
        print(f"OpenAI batch analyze error: {e}")
        return None


@app.route('/api/hub/add-batch', methods=['POST'])
@login_required
def hub_add_batch():
    """Добавить список слов в хаб через ИИ-анализ (пакетно)"""
    data = request.get_json() or {}
    student_id = _get_student_id_from_request(data)
    raw_text = data.get('text', '').strip()
    if not student_id or not raw_text:
        return jsonify({'ok': False, 'error': 'missing data'}), 400

    # Парсим слова: по строкам, запятым, точкам с запятой
    import re
    raw_words = re.split(r'[,;\n]+', raw_text)
    raw_words = [w.strip() for w in raw_words if w.strip()]

    if not raw_words:
        return jsonify({'ok': False, 'error': 'empty list'}), 400
    if len(raw_words) > 50:
        return jsonify({'ok': False, 'error': 'too_many', 'max': 50}), 400

    # Пакетный анализ через ИИ
    analyses = _analyze_korean_batch(raw_words)
    if not analyses:
        return jsonify({'ok': False, 'error': 'ai_failed'}), 500

    added_by = 'teacher' if session.get('role') == 'teacher' else 'student'
    added = []
    duplicates = []
    failed = []

    for i, analysis in enumerate(analyses):
        original = raw_words[i] if i < len(raw_words) else '?'
        base_form = (analysis.get('base') or '').strip()
        rus = (analysis.get('rus') or '').strip()

        if not base_form:
            failed.append(original)
            continue

        # Проверка дубликата
        existing = WordHub.query.filter_by(student_id=student_id, word_kor=base_form).first()
        if existing:
            duplicates.append({'word_kor': existing.word_kor, 'word_rus': existing.word_rus})
            continue

        word = WordHub(
            student_id=student_id,
            word_kor=base_form,
            word_rus=rus,
            original_form=original,
            part_of_speech=analysis.get('pos', ''),
            added_by=added_by,
        )
        db.session.add(word)
        try:
            db.session.flush()
            added.append({
                'id': word.id, 'word_kor': word.word_kor,
                'word_rus': word.word_rus, 'pos': word.part_of_speech,
                'is_learned': False, 'added_by': added_by,
            })
        except Exception:
            db.session.rollback()
            duplicates.append({'word_kor': base_form, 'word_rus': rus})

    db.session.commit()
    return jsonify({
        'ok': True,
        'added': added,
        'duplicates': duplicates,
        'failed': failed,
        'summary': {
            'added': len(added),
            'duplicates': len(duplicates),
            'failed': len(failed),
        }
    })


@app.route('/api/hub/add', methods=['POST'])
@login_required
def hub_add():
    """Добавить слово в хаб через ИИ-анализ"""
    data = request.get_json() or {}
    student_id = _get_student_id_from_request(data)
    raw_word = data.get('word', '').strip()
    if not student_id or not raw_word:
        return jsonify({'ok': False, 'error': 'missing data'}), 400

    # Проверяем дубликат по оригинальной форме
    existing = WordHub.query.filter_by(student_id=student_id, original_form=raw_word).first()
    if existing:
        return jsonify({'ok': True, 'duplicate': True, 'word': {
            'id': existing.id, 'word_kor': existing.word_kor,
            'word_rus': existing.word_rus, 'pos': existing.part_of_speech
        }})

    # Анализ через ИИ
    analysis = _analyze_korean_word(raw_word)
    if not analysis or not analysis.get('base'):
        return jsonify({'ok': False, 'error': 'ai_failed'}), 500

    base_form = analysis['base']
    # Проверяем дубликат по словарной форме
    existing = WordHub.query.filter_by(student_id=student_id, word_kor=base_form).first()
    if existing:
        return jsonify({'ok': True, 'duplicate': True, 'word': {
            'id': existing.id, 'word_kor': existing.word_kor,
            'word_rus': existing.word_rus, 'pos': existing.part_of_speech
        }})

    added_by = 'teacher' if session.get('role') == 'teacher' else 'student'
    word = WordHub(
        student_id=student_id,
        word_kor=base_form,
        word_rus=analysis.get('rus', ''),
        original_form=raw_word,
        part_of_speech=analysis.get('pos', ''),
        added_by=added_by,
    )
    db.session.add(word)
    db.session.commit()
    return jsonify({'ok': True, 'word': {
        'id': word.id, 'word_kor': word.word_kor,
        'word_rus': word.word_rus, 'pos': word.part_of_speech
    }})


@app.route('/api/hub/list', methods=['POST'])
@login_required
def hub_list():
    """Получить все слова хаба ученика"""
    data = request.get_json() or {}
    student_id = _get_student_id_from_request(data)
    if not student_id:
        return jsonify({'ok': False}), 400

    words = WordHub.query.filter_by(student_id=student_id)\
        .order_by(WordHub.created_at.desc()).all()
    return jsonify({'ok': True, 'words': [{
        'id': w.id, 'word_kor': w.word_kor, 'word_rus': w.word_rus,
        'original_form': w.original_form, 'pos': w.part_of_speech,
        'is_learned': w.is_learned, 'added_by': w.added_by,
    } for w in words]})


@app.route('/api/hub/toggle-learned', methods=['POST'])
@login_required
def hub_toggle_learned():
    """Переключить статус выученного слова"""
    data = request.get_json() or {}
    word_id = data.get('word_id')
    if not word_id:
        return jsonify({'ok': False}), 400

    word = WordHub.query.get(word_id)
    if not word:
        return jsonify({'ok': False}), 404

    word.is_learned = not word.is_learned
    db.session.commit()
    return jsonify({'ok': True, 'is_learned': word.is_learned})


@app.route('/api/hub/delete', methods=['POST'])
@login_required
def hub_delete():
    """Удалить слово из хаба"""
    data = request.get_json() or {}
    word_id = data.get('word_id')
    if not word_id:
        return jsonify({'ok': False}), 400

    word = WordHub.query.get(word_id)
    if word:
        db.session.delete(word)
        db.session.commit()
    return jsonify({'ok': True})


# ══════════════════════════════════════════
#  GOOGLE CLOUD TTS API
# ══════════════════════════════════════════

@app.route('/api/tts')
def api_tts():
    """Озвучка корейского текста через Google Cloud TTS REST API"""
    if not TTS_ENABLED:
        return jsonify({'error': 'TTS not configured'}), 503

    text = request.args.get('text', '').strip()
    if not text or len(text) > 1000:
        return jsonify({'error': 'Bad request'}), 400

    # Кеш по хешу текста
    filename = hashlib.md5(text.encode('utf-8')).hexdigest() + '.mp3'
    filepath = os.path.join(TTS_CACHE_DIR, filename)

    if not os.path.exists(filepath):
        try:
            resp = http_requests.post(
                f'https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_API_KEY}',
                json={
                    'input': {'text': text},
                    'voice': {'languageCode': 'ko-KR', 'ssmlGender': 'FEMALE'},
                    'audioConfig': {'audioEncoding': 'MP3'}
                },
                timeout=10
            )
            if resp.status_code != 200:
                print(f"TTS error: {resp.status_code} {resp.text[:200]}")
                return jsonify({'error': 'TTS failed'}), 500

            audio_bytes = base64.b64decode(resp.json()['audioContent'])
            with open(filepath, 'wb') as f:
                f.write(audio_bytes)
        except Exception as e:
            print(f"TTS error: {e}")
            return jsonify({'error': 'TTS synthesis failed'}), 500

    return send_file(filepath, mimetype='audio/mpeg')


# ══════════════════════════════════════════
#  МАРШРУТЫ ТРЕНАЖЁРОВ (учитель смотрит за учеником)
# ══════════════════════════════════════════

def _teacher_trainer(student_id, template):
    student = _owns_student(student_id)
    if not student:
        return redirect(url_for('select_student'))
    session['current_student_id'] = student_id
    session['current_student_name'] = student.name
    return render_template(template, student=student, student_mode=False)

@app.route('/student/<int:student_id>/trainers')
@teacher_required
def trainer_menu(student_id):
    return _teacher_trainer(student_id, 'trainer_menu.html')

@app.route('/student/<int:student_id>/trainer/alphabet')
@teacher_required
def trainer_alphabet(student_id):
    return _teacher_trainer(student_id, 'trainer_alphabet.html')

@app.route('/student/<int:student_id>/trainer/numbers')
@teacher_required
def trainer_numbers(student_id):
    return _teacher_trainer(student_id, 'trainer_numbers.html')

@app.route('/student/<int:student_id>/trainer/time')
@teacher_required
def trainer_time(student_id):
    return _teacher_trainer(student_id, 'trainer_time.html')

@app.route('/student/<int:student_id>/trainer/money')
@teacher_required
def trainer_money(student_id):
    return _teacher_trainer(student_id, 'trainer_money.html')

@app.route('/student/<int:student_id>/trainer/dates')
@teacher_required
def trainer_dates(student_id):
    return _teacher_trainer(student_id, 'trainer_dates.html')

@app.route('/student/<int:student_id>/trainer/colors')
@teacher_required
def trainer_colors(student_id):
    return _teacher_trainer(student_id, 'trainer_colors.html')

@app.route('/student/<int:student_id>/trainer/weekdays')
@teacher_required
def trainer_weekdays(student_id):
    return _teacher_trainer(student_id, 'trainer_weekdays.html')

@app.route('/student/<int:student_id>/trainer/weather')
@teacher_required
def trainer_weather(student_id):
    return _teacher_trainer(student_id, 'trainer_weather.html')

@app.route('/student/<int:student_id>/trainer/locations')
@teacher_required
def trainer_locations(student_id):
    return _teacher_trainer(student_id, 'trainer_locations.html')

@app.route('/student/<int:student_id>/trainer/verbs')
@teacher_required
def trainer_verbs(student_id):
    return _teacher_trainer(student_id, 'trainer_verbs.html')

@app.route('/student/<int:student_id>/trainer/sentences')
@teacher_required
def trainer_sentences(student_id):
    return _teacher_trainer(student_id, 'trainer_sentences.html')

@app.route('/student/<int:student_id>/trainer/grammar')
@teacher_required
def trainer_grammar(student_id):
    return _teacher_trainer(student_id, 'trainer_grammar.html')

@app.route('/student/<int:student_id>/trainer/text')
@teacher_required
def trainer_text(student_id):
    return _teacher_trainer(student_id, 'trainer_text.html')

@app.route('/student/<int:student_id>/trainer/cards')
@teacher_required
def trainer_cards(student_id):
    return _teacher_trainer(student_id, 'trainer_cards.html')

@app.route('/student/<int:student_id>/trainer/words')
@teacher_required
def trainer_words(student_id):
    return _teacher_trainer(student_id, 'trainer_words.html')

@app.route('/student/<int:student_id>/trainer/quiz')
@teacher_required
def trainer_quiz(student_id):
    return _teacher_trainer(student_id, 'trainer_quiz.html')

@app.route('/student/<int:student_id>/trainer/video')
@teacher_required
def trainer_video(student_id):
    return _teacher_trainer(student_id, 'trainer_video.html')

@app.route('/student/<int:student_id>/trainer/pictures')
@teacher_required
def trainer_pictures(student_id):
    return _teacher_trainer(student_id, 'trainer_pictures.html')

@app.route('/student/<int:student_id>/trainer/phrases')
@teacher_required
def trainer_phrases(student_id):
    return _teacher_trainer(student_id, 'trainer_phrases.html')

@app.route('/student/<int:student_id>/trainer/hub')
@teacher_required
def trainer_hub(student_id):
    return _teacher_trainer(student_id, 'trainer_hub.html')

@app.route('/student/<int:student_id>/history')
@teacher_required
def history(student_id):
    student = _owns_student(student_id)
    if not student:
        return redirect(url_for('select_student'))
    return render_template('history.html', student=student)


# ══════════════════════════════════════════
#  ПРОКСИ ВИДЕО С ЯНДЕКСА
# ══════════════════════════════════════════

@app.route("/content/<path:filepath>")
def proxy_yandex(filepath):
    """Проксирует запросы к видео-контенту на Яндексе"""
    yandex_url = f"https://kimchigo-telegram-miniapp-site.website.yandexcloud.net/{filepath}"
    try:
        resp = http_requests.get(yandex_url, timeout=15)
        return resp.content, resp.status_code, {
            "Content-Type": resp.headers.get("Content-Type", "application/octet-stream"),
            "Cache-Control": "public, max-age=3600"
        }
    except Exception as e:
        return str(e), 502


# ══════════════════════════════════════════
#  ИНИЦИАЛИЗАЦИЯ БД
# ══════════════════════════════════════════

with app.app_context():
    db.create_all()
    # Миграция: добавляем password_plain если его нет
    try:
        db.session.execute(db.text(
            "ALTER TABLE student_account ADD COLUMN password_plain VARCHAR(200) NOT NULL DEFAULT ''"
        ))
        db.session.commit()
        print("Миграция: добавлен столбец password_plain")
    except Exception:
        db.session.rollback()
    # Миграция: создаём таблицу word_hub если её нет
    try:
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS word_hub (
                id SERIAL PRIMARY KEY,
                student_id INTEGER NOT NULL REFERENCES student(id),
                word_kor VARCHAR(100) NOT NULL,
                word_rus VARCHAR(200) NOT NULL,
                original_form VARCHAR(100) NOT NULL,
                part_of_speech VARCHAR(50) DEFAULT '',
                is_learned BOOLEAN DEFAULT FALSE,
                added_by VARCHAR(20) DEFAULT 'teacher',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_student_word UNIQUE (student_id, word_kor)
            )
        """))
        db.session.commit()
        print("Миграция: таблица word_hub готова")
    except Exception:
        db.session.rollback()
    # Миграция: добавляем telegram_id в student
    try:
        db.session.execute(db.text(
            "ALTER TABLE student ADD COLUMN telegram_id VARCHAR(50) UNIQUE"
        ))
        db.session.commit()
        print("Миграция: добавлен столбец telegram_id")
    except Exception:
        db.session.rollback()
    # Миграция: делаем teacher_id nullable
    try:
        db.session.execute(db.text(
            "ALTER TABLE student ALTER COLUMN teacher_id DROP NOT NULL"
        ))
        db.session.commit()
        print("Миграция: teacher_id теперь nullable")
    except Exception:
        db.session.rollback()
    # Миграция: расширяем status в trainer_item_progress до TEXT (для хранения HTML маркеров)
    try:
        db.session.execute(db.text(
            "ALTER TABLE trainer_item_progress ALTER COLUMN status TYPE TEXT"
        ))
        db.session.commit()
        print("Миграция: trainer_item_progress.status расширен до TEXT")
    except Exception:
        db.session.rollback()
    if not Teacher.query.filter_by(username='admin').first():
        teacher = Teacher(
            username='admin',
            password_hash=generate_password_hash('admin')
        )
        db.session.add(teacher)
        db.session.commit()
        print('Создан тестовый учитель: admin/admin')

# ── Gemini News Bot (работает в фоновых потоках) ──
import bot

# ── Gemini Chat API (для внешнего приложения) ──
GEMINI_CHAT_SECRET = os.environ.get("GEMINI_CHAT_SECRET", "jarvis2026")

@app.route('/api/gemini/chat', methods=['POST'])
def api_gemini_chat():
    """Эндпоинт для чата с Gemini через внешнее приложение."""
    data = request.get_json(silent=True) or {}

    # Простая авторизация по секрету
    if data.get("secret") != GEMINI_CHAT_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    history = data.get("history", [])
    model = data.get("model", "")
    system_prompt = data.get("system_prompt", "")
    reply = bot.gemini_chat(message, history, model, system_prompt=system_prompt)
    return jsonify({"reply": reply})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
