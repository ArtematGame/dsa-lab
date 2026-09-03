from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)

# Сборка строки подключения из переменных окружения
DB_USER = os.getenv('POSTGRES_USER', 'app')
DB_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'changeme')
DB_HOST = os.getenv('POSTGRES_HOST', 'localhost')
DB_PORT = os.getenv('POSTGRES_PORT', '5432')
DB_NAME = os.getenv('POSTGRES_DB', 'visits_db')

app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Модель Visit с полями: 
# - id (первичный ключ)
# - visit_time (время обращения)
# - client_ip (IP-адрес клиента)
class Visit(db.Model):
    __tablename__ = 'visits'
    id = db.Column(db.Integer, primary_key=True)
    visit_time = db.Column(db.DateTime, nullable=False)
    client_ip = db.Column(db.String(45), nullable=False)

# Создание таблицы при старте приложения
with app.app_context():
    db.create_all()

# Маршрут GET /hello
@app.route('/hello')
def hello():
    # 1. Получаем текущее время
    # 2. Получаем IP-адрес клиента
    # 3. Сохраняем запись в таблицу Visit
    visit = Visit(
        visit_time=datetime.now(),
        client_ip=request.remote_addr
    )
    db.session.add(visit)
    db.session.commit()
    # 4. Возвращаем 200 OK с телом «Hello»
    return 'Hello', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)