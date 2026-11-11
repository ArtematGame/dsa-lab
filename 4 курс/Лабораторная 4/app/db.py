from datetime import datetime, time, timedelta, timezone
from sqlalchemy import MetaData, Table, Column, String, DateTime, Integer, Index, select
from .flights import Flight

# Описание таблицы рейсов 
metadata = MetaData()
flights = Table('flights', metadata,
    # Первичный ключ перевозчик + номер рейса + время вылета.
    Column('carrier', String(16), primary_key=True),                # перевозчик
    Column('number', String(16), primary_key=True),                 # номер рейса
    Column('origin', String(3), nullable=False),                    # аэропорт вылета
    Column('destination', String(3), nullable=False),               # аэропорт прилёта
    Column('departure', DateTime(timezone=True), primary_key=True), # время вылета
    Column('arrival', DateTime(timezone=True), nullable=False),     # время прилёта
    Column('price', Integer, nullable=False))                       # цена
# Индекс по времени вылета чтобы быстро выбирать рейсы за одну дату
Index('ix_flights_departure', flights.c.departure)

# запрос все рейсы, вылетающие в дату day
def query(day):
    start = datetime.combine(day, time(), timezone.utc)
    return select(flights).where(flights.c.departure >= start,
                                flights.c.departure < start + timedelta(days=1))

# СИНХРОННОЕ чтение 
# Поток ждёт ответа базы и в это время ничего другого не делает
def read_sync(engine, day):
    with engine.connect() as connection:
        rows = connection.execute(query(day)).all()
    return [Flight(*row) for row in rows]

# АСИНХРОННОЕ чтение
# На await цикл переключается на другие запросы
async def read_async(engine, day):
    async with engine.connect() as connection:
        result = await connection.execute(query(day))
        rows = result.all()
    return [Flight(*row) for row in rows]
