import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Используем SQLite для разработки
DATABASE_URL = "sqlite:///./visits.db"

# Создаем engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # Нужно для SQLite
)

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для моделей
Base = declarative_base()

# Функция для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()