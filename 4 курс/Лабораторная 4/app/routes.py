# составление маршрутов вынесено в отдельную функцию, которая НЕ обращается ни к сети, ни к базе  только вычисления
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import timedelta
from heapq import heappush, heapreplace

# flights все рейсы 
# origin откуда, destination куда, day дата поиска.
# Возвращает до 20 самых дешёвых маршрутов 
def build_routes(flights, origin, destination, day):
    # Группируем рейсы по аэропорту вылета
    # Берём только рейсы вылетающие в дату поиска 
    outgoing = defaultdict(list)
    for flight in flights:
        if flight.departure.date() == day:
            outgoing[flight.origin].append(flight)
    # В каждой группе сортируем рейсы по времени вылета
    for group in outgoing.values():
        group.sort(key=lambda f: (f.departure, f.carrier, f.number))
    # Отдельные списки времени вылета для быстрого двоичного поиска (bisect)
    departures = {airport: [f.departure for f in group] for airport, group in outgoing.items()}
    # best 20 лучших найденных маршрутов наверху всегда самый ДОРОГОЙ из лучших
    best = []
    serial = 0   # порядковый номер найденного маршрута 

    # Рекурсивный перебор
    def visit(airport, path, seen, cost):
        nonlocal serial
        # Долетели до места назначения запоминаем маршрут
        if airport == destination:
            serial += 1
            entry = (-cost, -serial, tuple(path))
            if len(best) < 20:
                heappush(best, entry)              # пока меньше 20 просто добавляем
            elif entry[:2] > best[0][:2]:
                heapreplace(best, entry)           # дешевле самого дорогого заменяем
            return
        # Уже 3 рейса (= 2 пересадки) дальше лететь нельзя.
        if len(path) == 3:
            return
        candidates = outgoing.get(airport, [])
        if path:
            # пересадка следующий рейс должен вылететь через 1–6 часов
            times = departures.get(airport, [])
            low = bisect_left(times, path[-1].arrival + timedelta(hours=1))
            high = bisect_right(times, path[-1].arrival + timedelta(hours=6))
            candidates = candidates[low:high]
        for flight in candidates:
            # Аэропорты в маршруте не должны повторяться
            if flight.destination in seen:
                continue
            new_cost = cost + flight.price
            #  уже есть 20 маршрутов, а этот уже дороже худшего из них продолжать бессмысленно 
            if len(best) == 20 and new_cost > -best[0][0]:
                continue
            visit(flight.destination, path + [flight], seen | {flight.destination}, new_cost)

    # Начинаем поиск из аэропорта вылета
    visit(origin, [], {origin}, 0)
    # Сортируем по возрастанию цены и превращаем в JSON
    return [{'price': -cost, 'flights': [f.json() for f in path]}
            for cost, index, path in sorted(best, key=lambda x: (-x[0], -x[1]))]
