# имитация внешней авиакомпании.
# Один и тот же код запускается тремя контейнерами различия через переменные докера
import asyncio
import os
import random
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from .flights import generate

app = FastAPI()
# Параметры поставщика из переменных окружения 
PROVIDER_ID = os.environ['PROVIDER_ID']                      # имя
MEAN_MS = float(os.environ['MEAN_DELAY_MS'])                 # средняя задержка, мс 
JITTER = float(os.getenv('JITTER', '0.3'))                   # разброс задержки:
ERROR_RATE = float(os.getenv('ERROR_RATE', '0.05'))          # доля ответов с ошибкой 500
SLOW_RATE = float(os.getenv('SLOW_RATE', '0'))               # доля ответов через 3 с 
FLIGHTS_PER_DAY = int(os.getenv('FLIGHTS_PER_DAY', '500'))   # рейсов в сутки

# рейсы поставщика за дату 
@app.get('/flights')
async def flights(date: date):
    # Задержка с вероятностью SLOW_RATE ровно 3 с,
    # иначе случайное значение от 0,7 до 1,3 средней
    delay = 3.0 if random.random() < SLOW_RATE else random.uniform(1-JITTER, 1+JITTER)*MEAN_MS/1000
    # С вероятностью ERROR_RATE ответ будет ошибкой 500.
    error = random.random() < ERROR_RATE
    # Задержка через await asyncio.sleep пока один запрос ждёт заглушка обслуживает другие
    await asyncio.sleep(delay)
    if error:
        raise HTTPException(500, 'Ошибка поставщика')
    # Рейсы генерируются при запросе для одной даты они всегда одинаковые
    return JSONResponse([f.json() for f in generate(date, PROVIDER_ID, FLIGHTS_PER_DAY)])

# проверка работоспособности 
@app.get('/health')
async def health():
    return {'status': 'ok'}
