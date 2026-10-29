# оценка среднего времени ответа по данным таблицы 1
import json,random
rng=random.Random(42)        
n=300000                     # число разыгранных запросов
means=[0.,0.,0.]             # суммы времён опроса каждого поставщика
sequential=parallel=0.       # суммы времени ответа для двух схем
for _ in range(n):
    times=[]
    # Параметры поставщиков: (средняя задержка, доля ответов через 3 с)
    for mean,slow in [(0.3,0),(0.5,0),(0.8,0.1)]:
        elapsed=0.
        for attempt in range(2):                     # первая попытка и повтор
            # Задержка 3 с с вероятностью slow, иначе среднее +- 30 %
            delay=3. if rng.random()<slow else rng.uniform(.7*mean,1.3*mean)
            error=rng.random()<.05                   # 5 % ответов ошибка 500
            elapsed=min(2.,elapsed+delay)            # больше 2 с не ждём
            # Выходим, если лимит исчерпан, ответ успешный или это уже повтор
            if elapsed>=2. or not error or attempt==1:break
            elapsed=min(2.,elapsed+.2)               # пауза 200 мс перед повтором
            if elapsed>=2.:break
        times.append(elapsed)
    for i,value in enumerate(times):means[i]+=value
    # ПООЧЕРЕДНО: сумма времён поставщиков + 35 мс (база 10 + маршруты 20 + ответ 5)
    sequential+=sum(times)+.035
    # ОДНОВРЕМЕННО: самое долгое из (база 10 мс, поставщики) + 25 мс (маршруты + ответ)
    parallel+=max(.010,*times)+.025
# ИТОГ средние времена поставщиков, обеих схем и расчёт по закону Литтла
print(json.dumps({'n':n,'seed':42,'provider_mean_s':[v/n for v in means],
                  'sequential_mean_s':sequential/n,'parallel_mean_s':parallel/n,
                  'little_requests':5*sequential/n,'little_db':.05},indent=2))
