# Нагрузочный скрипт 
# closed (замкнутый) C клиентов каждый шлёт следующий поиск только после ответа
# open(открытый) поиски идут с интенсивностью rate в секунду, не дожидаясь  ответов интервалы распределены по экспоненциальному закону
# Параллельно каждые 100 мс GET /health
import argparse
import asyncio
import json
import math
import random
import time
from datetime import timedelta
from pathlib import Path
import httpx
from app.flights import AIRPORTS, START_DATE, DAYS

# Подсчёт показателей по списку замеров rows
# duration длительность окна измерения end момент конца окна.
def statistics(rows, duration, end):
    times = sorted(row['latency_ms'] for row in rows)
    # Перцентиль методом ближайшего ранга
    def percentile(p):
        return times[max(0, math.ceil(p*len(times))-1)] if times else None
    # Сколько запросов завершилось до конца окна
    finished = sum(row['finished_s'] <= end for row in rows)
    return {'count': len(rows), 'completed_in_window': finished,
            'rps': finished/duration,                 # запросов в секунду 
            'sent_rps': len(rows)/duration,           # с какой частотой запросы отправлялись
            'p50_ms': percentile(.5), 'p95_ms': percentile(.95),
            'p99_ms': percentile(.99), 'max_ms': max(times) if times else None,
            'mean_ms': sum(times)/len(times) if times else None,
            # Доля ошибок
            'error_percent': 100*sum(row['error'] for row in rows)/len(rows) if rows else None}

async def run(args):
    # Генераторы с постоянным начальным значением
    # отправляется одинаковая последовательность запросов (воспроизводимость)
    query_rng = random.Random(args.seed)          # выбор аэропортов и дат
    arrivals_rng = random.Random(args.seed + 1)   # интервалы открытого режима
    search_rows, health_rows = [], []             # сюда складываются результаты
    pending = set()                               # запросы отправленные в фоне
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=200)
    # Два отдельных клиентадля поиска и для /health
    async with httpx.AsyncClient(base_url=args.url, timeout=args.timeout, limits=limits) as client, \
               httpx.AsyncClient(base_url=args.url, timeout=args.timeout, limits=limits) as health_client:
        # Временная шкала
        start = time.perf_counter()
        measure_start = start + args.warmup
        end = measure_start + args.duration

        # Отправить один запрос и записать результат
        async def request(path, params, rows, http_client):
            sent = time.perf_counter()
            status, error, message = None, False, None
            try:
                async with asyncio.timeout(args.timeout):   # тайм-аут клиента 30 с
                    response = await http_client.get(path, params=params)
                    status = response.status_code
                    error = status >= 400                    # ошибки
            except (TimeoutError, httpx.HTTPError) as exc:
                error, message = True, type(exc).__name__    # не дождались ответа ошибка
            finished = time.perf_counter()
            # Учитываем только запросы, отправленные внутри окна измерения
            if measure_start <= sent < end:
                rows.append({'sent_s': sent-start, 'finished_s': finished-start,
                             'latency_ms': (finished-sent)*1000, 'status': status,
                             'error': error, 'exception': message, 'params': params})

        # Случайные параметры поиска
        def params():
            origin, destination = query_rng.sample(AIRPORTS, 2)
            day = START_DATE + timedelta(days=query_rng.randrange(DAYS))
            return {'origin': origin, 'destination': destination, 'date': day.isoformat()}

        # Запустить запрос в фоне, не дожидаясь ответа
        def spawn(coroutine):
            task = asyncio.create_task(coroutine)
            pending.add(task)
            task.add_done_callback(pending.discard)

        # ЗАМКНУТЫЙ режим
        async def closed_client():
            while time.perf_counter() < end:
                await request('/search', params(), search_rows, client)

        # ОТКРЫТЫЙ режим
        async def open_stream():
            scheduled = start
            while True:
                scheduled += arrivals_rng.expovariate(args.rate)
                if scheduled >= end:
                    break
                await asyncio.sleep(max(0, scheduled-time.perf_counter()))
                spawn(request('/search', params(), search_rows, client))

        # Опрос /health каждые 100 мс во время всей нагрузки
        async def health_stream():
            scheduled = start
            while scheduled < end:
                await asyncio.sleep(max(0, scheduled-time.perf_counter()))
                spawn(request('/health', None, health_rows, health_client))
                scheduled += .1

        # Запуск
        workers = [closed_client() for _ in range(args.clients)] if args.mode == 'closed' else [open_stream()]
        await asyncio.gather(*workers, health_stream())
        # Дождаться запросов, которые ещё не завершились
        if pending:
            await asyncio.gather(*list(pending))
        elapsed = time.perf_counter()-start
    search_rows.sort(key=lambda row: row['sent_s'])
    health_rows.sort(key=lambda row: row['sent_s'])
    # в итоге получаем настройки, показатели поиска и /health, все исходные замеры
    data = {'config': vars(args), 'elapsed_with_drain_s': elapsed,
            'search': statistics(search_rows, args.duration, args.warmup+args.duration),
            'health': statistics(health_rows, args.duration, args.warmup+args.duration),
            'search_samples': search_rows, 'health_samples': health_rows}
    # Сохранить в JSON-файл и вывести показатели на экран
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in data.items() if not k.endswith('_samples')}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    # Параметры командной строки
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:8000')         # адрес сервиса
    parser.add_argument('--mode', choices=['closed','open'], required=True)  # режим нагрузки
    parser.add_argument('--clients', type=int, default=1)                 # C для замкнутого режима
    parser.add_argument('--rate', type=float, default=5)                  # запросов/с для открытого
    parser.add_argument('--duration', type=float, default=60)             # длительность замера, с
    parser.add_argument('--warmup', type=float, default=10)               # прогрев, с
    parser.add_argument('--timeout', type=float, default=30)              # тайм-аут клиента, с
    parser.add_argument('--seed', type=int, default=42)                   # начальное значение генератора
    parser.add_argument('--output', default='results/measurement.json')   # куда сохранить результат
    args = parser.parse_args()
    if min(args.clients,args.rate,args.duration,args.timeout) <= 0 or args.warmup < 0:
        parser.error('Параметры нагрузки должны быть положительными; прогрев неотрицателен')
    asyncio.run(run(args))
