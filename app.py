from flask import Flask, render_template, request, redirect, url_for, session, json, jsonify
from flask_sqlalchemy import SQLAlchemy
import bcrypt
import requests
import json

API_BASE_URL = "http://45.153.188.177:3001/features/"
api_url = "http://45.153.188.177:3001/features/?layer_id=8863"

app = Flask(__name__, template_folder='templates', static_folder='static') 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'secret_key'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))

    def __init__(self, username, password):
        self.username = username
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return redirect(url_for('login'))

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
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('soldat'))
        
        return render_template('login.html', error='Неверное имя пользователя или пароль')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/soldat')
def soldat():
    soldier_id = request.args.get('id')
    if not soldier_id:
        return render_template('soldat.html', soldier=None)

    try:
        soldier_url = f"{API_BASE_URL}{soldier_id}?layer_id=8863"
        response = requests.get(soldier_url)
        response.raise_for_status()
        soldier_data = response.json()

        # Проверка на наличие фото в ответе
        photo_url = None
        if soldier_data['extensions']['attachment']:
            photo_name = soldier_data['extensions']['attachment'][0]['name']
            # Формируем URL для фотографии
            photo_url = f"{API_BASE_URL}image/{photo_name}"

        return render_template('soldat.html', soldier=soldier_data['fields'], soldier_photo=photo_url)
    except requests.exceptions.RequestException:
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
            {'id': soldier['id'], 'fio': soldier['fields'].get('fio', 'Неизвестно')}
            for soldier in data if 'fields' in soldier and query.lower() in soldier['fields'].get('fio', '').lower()
        ]

        return render_template('search.html', results=results)
    except requests.exceptions.RequestException:
        return render_template('search.html', error="Ошибка при получении данных", results=[])




@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

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
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
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



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
