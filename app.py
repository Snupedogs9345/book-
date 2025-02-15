from flask import Flask, render_template, request, redirect, url_for, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
import logging
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
db = SQLAlchemy(app)

# Настройка логирования
logging.basicConfig(filename='app.log', level=logging.INFO)

participant_conflict = db.Table('participant_conflict',
    db.Column('participant_id', db.Integer, db.ForeignKey('participant.id'), primary_key=True),
    db.Column('conflict_id', db.Integer, db.ForeignKey('conflict.id'), primary_key=True)
)

class Municipality(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    geom = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Модель пользователя
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    full_name = db.Column(db.String(100), nullable=True)  # ФИО
    position = db.Column(db.String(100), nullable=True)  # Должность
    phone = db.Column(db.String(20), nullable=True)      # Телефон


class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    login = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Модель авторизованного пользователя
class AuthorizedUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    organization = db.Column(db.String(100), nullable=False)
    login = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(100), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)  # Подтверждение администратора
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'))  # Связь с администратором

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Модель записи в Книгу
class BookEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Черновик')  # Статус: Черновик или Опубликовано
    user_id = db.Column(db.Integer, db.ForeignKey('authorized_user.id'))  # Связь с пользователем
    admin_id = db.Column(db.Integer, db.ForeignKey('admin.id'))  # Связь с администратором
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)  # Новое поле
    contact = db.Column(db.String(100), nullable=False)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Активен')
    conflicts = db.relationship('Conflict', secondary=participant_conflict, 
                              backref=db.backref('participants', lazy='dynamic'))

class Conflict(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default=('open'))  # open/closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Инициализация Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Декоратор для проверки админских прав
def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_admin:
            return abort(403)
        return func(*args, **kwargs)
    return decorated_view

# Маршруты аутентификации
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user:
            print(f"User found: {user.username}")
            if check_password_hash(user.password, password):
                print("Password is correct")
                login_user(user)
                return redirect(url_for('admin_panel'))
            else:
                print("Incorrect password")
        else:
            print("User not found")
        return "Неверные учетные данные"
    return render_template('admin/login.html')
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Маршруты админ-панели
@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    return render_template('admin/base.html')

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_users():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        organization = request.form.get('organization')
        login = request.form.get('login')
        password = request.form.get('password')
        user = AuthorizedUser(full_name=full_name, phone=phone, organization=organization, login=login)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('manage_users'))
    users = AuthorizedUser.query.all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/logs')
@login_required
@admin_required
def view_logs():
    with open('app.log', 'r') as f:
        logs = f.readlines()
    return render_template('admin/logs.html', logs=logs)

# Пример форматно-логического контроля
@app.route('/admin/control', methods=['GET', 'POST'])
@login_required
@admin_required
def format_control():
    if request.method == 'POST':
        data = request.form.get('data')
        if not data.isdigit():
            return "Ошибка формата данных!"
        logging.info(f'[{datetime.now()}] Контроль данных: {data}')
        return "Данные прошли проверку"
    return render_template('admin/control.html')

@app.route('/admin/admins', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_admins():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        position = request.form.get('position')
        phone = request.form.get('phone')
        login = request.form.get('login')
        password = request.form.get('password')
        
        # Создаем пользователя с флагом is_admin=True
        admin = User(
            username=login,  # Используем login как username
            password=generate_password_hash(password),  # Хешируем пароль
            is_admin=True  # Устанавливаем флаг администратора
        )
        
        db.session.add(admin)
        db.session.commit()
        return redirect(url_for('manage_admins'))
    
    # Получаем всех пользователей с флагом is_admin=True
    admins = User.query.filter_by(is_admin=True).all()
    return render_template('admin/admins.html', admins=admins)

@app.route('/admin/entries', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_entries():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        user_id = request.form.get('user_id')
        entry = BookEntry(title=title, content=content, user_id=user_id, admin_id=current_user.id)
        db.session.add(entry)
        db.session.commit()
        return redirect(url_for('manage_entries'))
    entries = BookEntry.query.all()
    return render_template('admin/entries.html', entries=entries)

@app.route('/approve_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    user = AuthorizedUser.query.get_or_404(user_id)  # Находим пользователя по ID
    user.is_approved = True  # Одобряем пользователя
    db.session.commit()  # Сохраняем изменения в базе данных
    return redirect(url_for('manage_users'))  # Перенаправляем обратно на страницу управления пользователями


@app.route('/admin/municipalities')
@login_required
@admin_required
def list_municipalities():
    municipalities = Municipality.query.all()
    return render_template('list_municipalities.html', municipalities=municipalities)


@app.route('/admin/municipalities/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_municipality():
    if request.method == 'POST':
        name = request.form.get('name')
        geom = request.form.get('geom')
        
        if not name or not geom:
            return "Все поля обязательны для заполнения", 400
            
        new_municipality = Municipality(name=name, geom=geom)
        db.session.add(new_municipality)
        db.session.commit()
        return redirect(url_for('list_municipalities'))
    
    return render_template('admin/add_municipality.html')

@app.route('/admin/municipalities/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_municipality(id):
    municipality = Municipality.query.get_or_404(id)
    
    if request.method == 'POST':
        municipality.name = request.form.get('name')
        municipality.geom = request.form.get('geom')
        db.session.commit()
        return redirect(url_for('list_municipalities'))
    
    return render_template('admin/edit_municipality.html', municipality=municipality)

@app.route('/admin/municipalities/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_municipality(id):
    municipality = Municipality.query.get_or_404(id)
    db.session.delete(municipality)
    db.session.commit()
    return redirect(url_for('list_municipalities'))

# Список участников
@app.route('/admin/participants')
@login_required
@admin_required
def list_participants():
    participants = Participant.query.all()
    return render_template('list_participants.html', participants=participants)


@app.route('/admin/participants/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_participant():
    all_conflicts = Conflict.query.all()
    
    if request.method == 'POST':
        # ... существующий код ...
        new_participant = Participant(
            full_name=request.form['full_name'],
            description=request.form['description'],
            contact=request.form['contact'],
            status=request.form['status']
        )
        
        # Добавляем связи с конфликтами
        conflict_ids = request.form.getlist('conflicts')
        selected_conflicts = Conflict.query.filter(Conflict.id.in_(conflict_ids)).all()
        new_participant.conflicts = selected_conflicts
        
        db.session.add(new_participant)
        db.session.commit()
        return redirect(url_for('list_participants'))
    
    return render_template('admin/add_participant.html', all_conflicts=all_conflicts)

@app.route('/admin/participants/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_participant(id):
    participant = Participant.query.get_or_404(id)
    all_conflicts = Conflict.query.all()
    
    if request.method == 'POST':
        # ... существующий код ...
        participant.description = request.form['description']
        
        # Обновляем связи с конфликтами
        conflict_ids = request.form.getlist('conflicts')
        selected_conflicts = Conflict.query.filter(Conflict.id.in_(conflict_ids)).all()
        participant.conflicts = selected_conflicts
        
        db.session.commit()
        return redirect(url_for('list_participants'))
    
    return render_template('admin/edit_participant.html', 
                         participant=participant,
                         all_conflicts=all_conflicts)

@app.route('/admin/participants/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_participant(id):
    participant = Participant.query.get_or_404(id)
    db.session.delete(participant)
    db.session.commit()
    return redirect(url_for('list_participants'))

# Список конфликтов
@app.route('/admin/conflicts')
@login_required
@admin_required
def list_conflicts():
    conflicts = Conflict.query.all()
    return render_template('list_conflicts.html', conflicts=conflicts)

@app.route('/admin/conflicts/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_conflict():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        status = request.form.get('status', 'open')
        
        if not title or not description:
            return "Все поля обязательны для заполнения", 400
            
        new_conflict = Conflict(
            title=title,
            description=description,
            status=status
        )
        db.session.add(new_conflict)
        db.session.commit()
        return redirect(url_for('list_conflicts'))
    
    return render_template('admin/add_conflict.html')

@app.route('/admin/conflicts/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_conflict(id):
    conflict = Conflict.query.get_or_404(id)
    
    if request.method == 'POST':
        conflict.title = request.form.get('title')
        conflict.description = request.form.get('description')
        conflict.status = request.form.get('status')
        db.session.commit()
        return redirect(url_for('list_conflicts'))
    
    return render_template('admin/edit_conflict.html', conflict=conflict)

@app.route('/admin/conflicts/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_conflict(id):
    conflict = Conflict.query.get_or_404(id)
    db.session.delete(conflict)
    db.session.commit()
    return redirect(url_for('list_conflicts'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            hashed_pw = generate_password_hash('admin123')
            admin = User(
                username='admin',
                password=hashed_pw,
                is_admin=True,
                full_name='Администратор',
                position='Главный администратор',
                phone='+71234567890'
            )
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True)