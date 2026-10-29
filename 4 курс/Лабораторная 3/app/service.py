# Сервис поиска авиаперелётов 
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import date
import httpx
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from .db import read_sync, read_async
from .flights import AIRPORTS, Flight
from .routes import build_routes

# Какую версию запускать (по умолчанию синхронную)
VERSION = os.getenv('SERVICE_VERSION', 'sync')
# Три поставщика имя и адрес
PROVIDERS = [(f'P{i}', os.getenv(f'PROVIDER_{i}_URL', f'http://provider{i}:8000')) for i in range(1, 4)]

# lifespan выполняется один раз при запуске приложения (до yield) и при остановке (после yield)
# что бы соединения каждый раз не открывались заново
@asynccontextmanager
async def lifespan(app):
    if VERSION == 'async':
        # Асинхронный движок SQLAlchemy с драйвером asyncpg и асинхронный HTTP-клиент
        app.state.engine = create_async_engine(os.environ['ASYNC_DATABASE_URL'], pool_size=10, max_overflow=30)
        # timeout=None: время ожидания ограничиваем сами через asyncio.timeout 
        app.state.client = httpx.AsyncClient(timeout=None)
    else:
        # Синхронный движок с драйвером psycopg 
        # Пул до 40 соединений по числу потоков FastAPI
        app.state.engine = create_engine(os.environ['DATABASE_URL'], pool_size=10, max_overflow=30)
    yield   # здесь приложение работает
    # закрываем соединения.
    if VERSION == 'async':
        await app.state.client.aclose()
        await app.state.engine.dispose()
    else:
        app.state.engine.dispose()

app = FastAPI(lifespan=lifespan)

# Опрос одного поставщика СИНХРОННО 
# на поставщика 2 с вместе с повтором; после ошибки — пауза 200 мс и один повтор. Возвращает список рейсов или None, если поставщик не ответил
def provider_sync(url, day):
    # Общий срок на обе попытки сейчас + 2 секунды
    deadline = time.perf_counter() + 2.0
    for attempt in range(2):                      # попытка 0 первая 1 повтор
        # Сколько времени ещё осталось из 2 с
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return None
        try:
            # requests поток стоит, пока не придёт ответ
            # перед каждой попыткой передаём остаток срока
            response = requests.get(url + '/flights', params={'date': day.isoformat()}, timeout=remaining)
            response.raise_for_status()           # ответ 500 исключение
            result = [Flight.from_json(row) for row in response.json()]
            # Ответ засчитывается, только если уложились в 2 с
            return result if time.perf_counter() <= deadline else None
        except (requests.RequestException, ValueError, KeyError, TypeError):
            # Ошибка если это уже повтор или после паузы не останется времени сдаемся
            if attempt == 1 or deadline - time.perf_counter() <= .2:
                return None
            # Пауза 200 мс перед повтором time.sleep БЛОКИРУЮЩИЙ вызов
            time.sleep(.2)
    return None

# Опрос одного поставщика
# Те же правила, но пока ждём поставщика цикл событий обслуживает другие запросы
async def provider_async(client, url, day):
    try:
        # asyncio.timeout(2.0) ограничивает первую попытку паузу и повтор вместе если не уложились выдаст TimeoutError
        async with asyncio.timeout(2.0):
            for attempt in range(2):
                try:
                    # Асинхронный HTTP-запрос
                    response = await client.get(url + '/flights', params={'date': day.isoformat()})
                    response.raise_for_status()   # ответ 500 исключение
                    return [Flight.from_json(row) for row in response.json()]
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    if attempt == 1:              # повтор тоже неудачный
                        return None
                    # Пауза 200 мс не блокирующая сервис
                    await asyncio.sleep(.2)
    except TimeoutError:
        # 2 секунды истекли поставщик считается не ответившим.
        return None

# Проверка входных данных оба аэропорта из списка и не совпадают
def validate(origin, destination):
    if origin not in AIRPORTS or destination not in AIRPORTS or origin == destination:
        raise HTTPException(422, 'Нужны два различных аэропорта из расписания')

# собрать рейсы, составить маршруты, сформировать ответ
# own рейсы из своей базы results ответы трёх поставщиков started момент начала обработки запроса.
def finish(own, results, origin, destination, day, started):
    # Какие поставщики не ответили 
    missing = [name for (name, _), value in zip(PROVIDERS, results)
               if value is None or isinstance(value, Exception)]
    # своя база + ответившие поставщики
    all_flights = list(own)
    for value in results:
        if value is not None and not isinstance(value, Exception):
            all_flights.extend(value)
    # Не ответил ни один поставщик и в базе нет рейсов вернуть «Поиск временно недоступен».
    if not own and len(missing) == 3:
        return JSONResponse(status_code=503, content={'message': 'Поиск временно недоступен',
            'routes': [], 'unavailable_providers': missing,
            'processing_ms': round((time.perf_counter()-started)*1000, 3)})
    # Составление маршрутов (routes.py)
    routes = build_routes(all_flights, origin, destination, day)
    # маршруты, не ответившие поставщики, время обработки
    return JSONResponse({'routes': routes, 'unavailable_providers': missing,
            'processing_ms': round((time.perf_counter()-started)*1000, 3)})

# Синхронная обработка поиска
# База поставщик 1 поставщик 2 поставщик 3 маршруты
def search_sync(origin, destination, day):
    started = time.perf_counter()
    validate(origin, destination)
    own = read_sync(app.state.engine, day)                        
    results = [provider_sync(url, day) for _, url in PROVIDERS]   
    return finish(own, results, origin, destination, day, started)

# Регистрация обработчиков в зависимости от версии.
if VERSION == 'sync':
    # Обработчики через def
    # Блокирующий вызов занимает только свой поток
    @app.get('/search')
    def search(origin: str, destination: str, date: date):
        return search_sync(origin, destination, date)

    @app.get('/health')
    def health():
        return {'status': 'ok'}
elif VERSION == 'blocking_async':
    # меняются только объявления обработчиков.
    # Теперь обработчик выполняется прямо в цикле событий (один поток), а внутри блокирующие весь сервис стоит
    @app.get('/search')
    async def search(origin: str, destination: str, date: date):
        return search_sync(origin, destination, date)

    @app.get('/health')
    async def health():
        return {'status': 'ok'}
elif VERSION == 'async':
    # Полноценная асинхронная версия
    @app.get('/search')
    async def search(origin: str, destination: str, date: date):
        started = time.perf_counter()
        validate(origin, destination)
        # asyncio.gather запускает чтение базы и опрос трёх поставщиков ОДНОВРЕМЕННО
        # return_exceptions=True ошибка одной ветви не прерывает остальные
        own, *results = await asyncio.gather(read_async(app.state.engine, date),
            *(provider_async(app.state.client, url, date) for _, url in PROVIDERS),
            return_exceptions=True)
        # Если упала сама база отвечаем 503 
        if isinstance(own, Exception):
            raise HTTPException(503, 'База данных недоступна')
        return finish(own, results, origin, destination, date, started)

    @app.get('/health')
    async def health():
        return {'status': 'ok'}
else:
    raise ValueError(f'Неизвестная версия: {VERSION}')
