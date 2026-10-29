# Загрузка собственной базы рейсов
import os
from dataclasses import asdict
from datetime import timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert
from .db import metadata, flights
from .flights import generate, START_DATE, DAYS

def main():
    # Подключение к базе адрес берётся из переменной окружения 
    engine = create_engine(os.environ['DATABASE_URL'])
    # Создать таблицу и индекс, если их ещё нет
    metadata.create_all(engine)
    # Одна транзакция на всю загрузку
    with engine.begin() as connection:
        # 180 000 рейсов
        for offset in range(DAYS):
            day = START_DATE + timedelta(days=offset)
            rows = [asdict(f) for f in generate(day, 'OWN', 1500)]
            # если такой рейс уже есть он пропускается
            statement = insert(flights).values(rows).on_conflict_do_nothing()
            connection.execute(statement)
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        # ANALYZE обновляет статистику таблицы, чтобы PostgreSQL выбрал индекс
        connection.execute(text('ANALYZE flights'))
        print('Рейсов в базе:', connection.execute(text('SELECT count(*) FROM flights')).scalar())
    engine.dispose()

if __name__ == '__main__':
    main()
