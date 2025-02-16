from flask import Flask, render_template, request, redirect, url_for, session, json, jsonify
from flask_sqlalchemy import SQLAlchemy
import bcrypt
import requests
import json
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

logging.basicConfig(level=logging.DEBUG)

API_BASE_URL = "http://45.153.188.177:3002/features/?layer_id=8863"
api_url = "http://45.153.188.177:3002/features/?layer_id=8863"

app = Flask(__name__, template_folder='templates', static_folder='static') 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'secret_key'
db = SQLAlchemy(app)


@app.before_request
def log_request_info():
    logging.debug(f"Запрос: {request.method} {request.url}")
    logging.debug(f"Данные: {request.get_data()}")

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))

    def __init__(self, username, password):
        self.username = username
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))




class UserInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100))
    surname = db.Column(db.String(100))
    # Добавьте другие поля, которые вам нужны

    def __init__(self, user_id, email, name, surname):
        self.user_id = user_id
        self.email = email
        self.name = name
        self.surname = surname

with app.app_context():
    db.create_all()
        
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/callback')
def callback():
    # Получаем код авторизации из запроса
    code = request.args.get('code')
    if not code:
        return render_template('callback.html', error="Ошибка: код авторизации не найден в URL")

    try:
        # Обмениваем код на токены
        token_url = "https://lk.orb.ru/oauth/token"
        response = requests.post(token_url, data={
            'client_id': "32",  # Ваш client_id
            'client_secret': "fidgv44UV8gDzuViR5HMw2leMZ7JJncPtdifKHfJ",  # Ваш client_secret
            'redirect_uri': "http://hackathon-3.orb.ru/callback",  # Адрес редиректа
            'code': code,
            'grant_type': 'authorization_code'
        })
        response.raise_for_status()

        # Получаем токены
        tokens = response.json()
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')

        # Сохраняем токены в сессии
        session['access_token'] = access_token
        session['refresh_token'] = refresh_token

        # Получаем данные пользователя из ЕЛК (например, email)
        user_info_url = "https://lk.orb.ru/api/get_user"  # Пример URL для получения данных пользователя
        headers = {"Authorization": f"Bearer {access_token}"}
        user_info_response = requests.get(user_info_url, headers=headers)
        user_info_response.raise_for_status()

        user_info = user_info_response.json()
        user_email = user_info.get("user", {}).get("email")  # Предположим, что email возвращается в ответе
        user_id = user_info.get("user", {}).get("id")  # Получаем id пользователя

        print("----------------------")
        print(user_info_response.json())   
        print("----------------------")

        # Ищем или создаем пользователя в базе данных
        user = User.query.filter_by(username=user_email).first()
        if not user:
            # Создаем нового пользователя
            user = User(username=user_email, password="default_password")  # Пароль можно сгенерировать или оставить пустым
            db.session.add(user)
            db.session.commit()

        # Сохраняем user_id в сессии
        session['user_id'] = user.id

        # Сохраняем данные пользователя в таблицу UserInfo
        user_info_record = UserInfo.query.filter_by(user_id=user.id).first()
        if not user_info_record:
            user_info_record = UserInfo(
                user_id=user.id,
                email=user_email,
                name=None,  # Если есть дополнительные данные, их можно добавить
                surname=None
            )
            db.session.add(user_info_record)
            db.session.commit()

        # Перенаправляем пользователя на главную страницу
        return redirect(url_for('home'))

    except requests.exceptions.RequestException as e:
        return render_template('callback.html', error=f"Ошибка при получении токенов: {e}")

@app.route('/login_elk')
def login_elk():
    # URL для авторизации через ЕЛК
    auth_url = (
        "https://lk.orb.ru/oauth/authorize?"
        f"client_id=32&"  # Ваш client_id
        f"redirect_uri=http://hackathon-3.orb.ru/callback&"  # Адрес редиректа
        f"response_type=code&"
        f"scope=email+auth_method&"
        f"state=http://hackathon-3.orb.ru"  # Любое состояние (можно изменить)
    )
    return redirect(auth_url)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_template('register.html', error='Имя пользователя уже существует')
        
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Проверяем, авторизован ли пользователь
    if 'user_id' in session:
        return redirect(url_for('dashboard'))  # Перенаправляем на dashboard.html, если пользователь уже авторизован

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))  # Перенаправляем на dashboard.html после успешной авторизации
        
        return render_template('login.html', error='Неверное имя пользователя или пароль')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('access_token', None)
    session.pop('refresh_token', None)
    return redirect(url_for('login'))

@app.route('/soldat')
def soldat():
    soldier_id = request.args.get('id')
    if not soldier_id:
        return render_template('soldat.html', soldier=None)

    try:
        soldier_url = "http://45.153.188.177:3002/features/?layer_id=8863"
        response = requests.get(soldier_url)
        response.raise_for_status()

        soldiers_data = response.json()  # Убираем .get("features", [])

        # Проверяем, что получили список
        if not isinstance(soldiers_data, list):
            print("Ошибка: API вернул не список")
            return render_template('soldat.html', soldier=None)

        # Поиск нужного солдата по ID
        soldier_data = next((s for s in soldiers_data if str(s.get("id")) == soldier_id), None)
        if not soldier_data:
            return render_template('soldat.html', soldier=None)

        soldier_fields = soldier_data.get('fields', {})

        # Проверяем наличие фото
        photo_url = None
        attachments = soldier_data.get('extensions', {}).get('attachment', [])
        if attachments:
            photo_name = attachments[0].get('name')
            if photo_name:
                photo_url = f"http://45.153.188.177:3002/images/{photo_name}"

        return render_template('soldat.html', soldier=soldier_fields, soldier_photo=photo_url)
    except requests.exceptions.RequestException as e:
        print(f"Ошибка запроса: {e}")
        return render_template('soldat.html', soldier=None)

@app.route('/autocomplete')
def autocomplete():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify([])

    try:
        response = requests.get(API_BASE_URL)
        response.raise_for_status()
        data = response.json()

        results = [
            {'id': soldier['id'], 'fio': soldier['fields'].get('fio', 'Неизвестно')}
            for soldier in data if 'fields' in soldier and query.lower() in soldier['fields'].get('fio', '').lower()
        ][:10]  # Ограничиваем до 10 результатов

        return jsonify(results)
    except requests.exceptions.RequestException:
        return jsonify([])

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip()
    if not query:
        return render_template('search.html', error="Введите имя для поиска", results=[])

    try:
        response = requests.get(API_BASE_URL)  # Получаем всех пользователей
        response.raise_for_status()
        data = response.json()

        results = [
            {
                'id': soldier['id'],
                'fio': soldier['fields'].get('fio', 'Неизвестно'),
                'years': soldier['fields'].get('years', 'Неизвестно')  # Добавляем годы жизни
            }
            for soldier in data if 'fields' in soldier and query.lower() in soldier['fields'].get('fio', '').lower()
        ]

        return render_template('search.html', results=results)
    except requests.exceptions.RequestException:
        return render_template('search.html', error="Ошибка при получении данных", results=[])

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])  # Получаем пользователя из базы
    if not user:
        return redirect(url_for('logout'))  # Если пользователь не найден, разлогиниваем

    return render_template('dashboard.html', user=user)

@app.route('/map')
def map():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('map.html')

@app.route('/faq')
def faq():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('faq.html')

@app.route('/support', methods=['GET', 'POST'])
def support():
    # if 'user_id' not in session:
    #     return redirect(url_for('login'))
    
    if request.method == 'POST':
        message = request.form['message']
        return redirect(url_for('soldat'))
    
    return render_template('support.html')

# api
@app.route('/api/data')  # Новый маршрут для данных
def api_data():
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        data = response.json()
        if len(data) > 6 and 'fields' in data[6]:
            return jsonify(data[6]['fields'])  # Возвращаем данные из API
        else:
            return jsonify({"error": "Данные не найдены"})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Ошибка при запросе к API: {e}"})
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Ошибка декодирования JSON: {e}"})
    except Exception as e:
        return jsonify({"error": f"Другая ошибка: {e}"})

# smpt
def send_mes(user_email, message):
    sender = "prostor@prostor-dev.store"  # Ваш email для отправки
    password = "RostProsto_491"  # Пароль от вашего email
    server = smtplib.SMTP("smtp.beget.com", 2525)
    server.starttls()

    try:
        server.login(sender, password)
        # Формируем сообщение для пользователя
        email_content = f"Здравствуйте!\n\nСпасибо за ваше сообщение в службу поддержки.\n\nМы получили следующее сообщение от вас:\n\n{message}\n\nНаша команда свяжется с вами в ближайшее время.\n\nС уважением,\nКоманда ПРОСТОР."
        msg = MIMEText(email_content, "plain", "utf-8")
        msg["From"] = formataddr((str(Header("ПРОСТОР", "utf-8")), sender))
        msg["To"] = user_email
        msg["Subject"] = 'Ваше сообщение в службу поддержки ПРОСТОР'
        server.sendmail(sender, user_email, msg.as_string())
        return True
    except Exception as _ex:
        print(f"{_ex}\nCheck your login or password please!")
        return False
    finally:
        server.quit()

@app.route('/send_message', methods=['POST'])
def send_message():
    user_email = request.form.get('email')
    message = request.form.get('message')
    if user_email and message:
        if send_mes(user_email, message):
            flash('Сообщение успешно отправлено! На ваш email отправлено подтверждение.', 'success')
        else:
            flash('Ошибка при отправке сообщения. Пожалуйста, попробуйте еще раз.', 'danger')
    else:
        flash('Пожалуйста, заполните все поля.', 'danger')
    return redirect(url_for('support'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
