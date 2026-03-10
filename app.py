from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from functools import wraps
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///korean_learning.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)

class StudentAccount(db.Model):
    """Логин/пароль для ученика — создаётся учителем"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    password_plain = db.Column(db.String(200), nullable=False, default="")  # открытый пароль для учителя
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)  # учитель может заблокировать
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student', backref=db.backref('account', uselist=False))

class Note(db.Model):
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
        return redirect(url_for('student_trainers'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        login_as = request.form.get('login_as', 'teacher')  # скрытое поле в форме

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
                    return redirect(url_for('student_trainers'))
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
        # Удаляем аккаунт ученика если есть
        if student.account:
            db.session.delete(student.account)
        Note.query.filter_by(student_id=student_id).delete()
        ModuleProgress.query.filter_by(student_id=student_id).delete()
        SessionLog.query.filter_by(student_id=student_id).delete()
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

    return render_template('dashboard.html',
        student=student,
        total_exercises=total_exercises,
        active_modules=active_modules,
        last_active=last_active
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
    }
    template = template_map.get(module)
    if not template:
        return redirect(url_for('student_trainers'))
    return render_template(template, student=student, student_mode=True)


# ══════════════════════════════════════════
#  PROGRESS API  (работает для обоих ролей)
# ══════════════════════════════════════════

def _get_student_id_from_request(data):
    """Определяет student_id в зависимости от роли"""
    if session.get('role') == 'student':
        return session.get('student_id')
    return data.get('student_id')  # учитель передаёт явно

@app.route('/api/progress/ping', methods=['POST'])
@login_required
def progress_ping():
    """Вызывается при входе в тренажёр — логирует начало сессии"""
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

@app.route('/student/<int:student_id>/history')
@teacher_required
def history(student_id):
    student = _owns_student(student_id)
    if not student:
        return redirect(url_for('select_student'))
    return render_template('history.html', student=student)


# ══════════════════════════════════════════
#  ИНИЦИАЛИЗАЦИЯ БД
# ══════════════════════════════════════════

with app.app_context():
    db.create_all()
    if not Teacher.query.filter_by(username='admin').first():
        teacher = Teacher(
            username='admin',
            password_hash=generate_password_hash('admin')
        )
        db.session.add(teacher)
        db.session.commit()
        print('Создан тестовый учитель: admin/admin')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
