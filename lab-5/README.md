# Бонусная программа сети магазинов

<!-- Назначение сервисов, их взаимодействие и запуск приложения. -->

Микросервисное приложение для учёта бонусных баллов покупателей.  
Кассы магазинов отправляют операции (покупка, возврат, оплата баллами), система асинхронно пересчитывает балансы и рассылает события подписчикам.

**Стек:** Python 3.11, FastAPI, SQLAlchemy 2.0 (asyncpg), aio-pika, PostgreSQL 17, RabbitMQ 4, Docker Compose.

---

## Содержание

1. [Архитектура](#архитектура)
2. [Предметная область](#предметная-область)
3. [Микросервисы](#микросервисы)
4. [Поток данных](#поток-данных)
5. [RabbitMQ](#rabbitmq)
6. [База данных](#база-данных)
7. [API](#api)
8. [Конфигурация](#конфигурация)
9. [Запуск](#запуск)
10. [Проверка работоспособности](#проверка-работоспособности)
11. [Структура репозитория](#структура-репозитория)
12. [Причины отклонения операций](#причины-отклонения-операций)

---

## Архитектура

Приложение состоит из **6 Docker-контейнеров**:

| Контейнер   | Назначение                                      | Порт  |
|-------------|--------------------------------------------------|-------|
| **api**     | Приём операций, выдача балансов и результатов    | 8000  |
| **worker**  | Обработка операций, расчёт баллов, публикация событий | — |
| **notifier**| Уведомления покупателям                          | 8001  |
| **analytics**| Статистика по магазинам                         | 8002  |
| **postgres**| База данных бонусной программы                   | —     |
| **rabbitmq**| Брокер сообщений (панель управления)             | 15672 |

Каждый микросервис (api, worker, notifier, analytics) — **отдельное приложение** со своим каталогом, `Dockerfile` и образом.  
Сервисы не вызывают друг друга напрямую: связь только через RabbitMQ и (для api/worker) через общую БД.

```
Касса
  │
  ▼
 api  ──publish──►  exchange «loyalty» (direct)
                         │
                         ▼
                   queue «operations»
                         │
                         ▼
                      worker
                    ┌────┴────┐
                    │         │
               PostgreSQL   exchange «loyalty.events» (fanout)
                              │
                 ┌────────────┼────────────┐
                 ▼                         ▼
          queue notifier.events     queue analytics.events
                 │                         │
                 ▼                         ▼
             notifier                  analytics
```

---

## Предметная область

Сеть магазинов ведёт бонусную программу. У каждого покупателя есть бонусный счёт (1 балл = 1 ₽ при оплате).

### Виды операций

| type       | Описание | Обязательные поля |
|------------|----------|-------------------|
| `purchase` | Покупка. Начисление **5 %** от суммы чека (дробная часть отбрасывается) | `amount` > 0 |
| `return`   | Возврат всего чека. Списание баллов, начисленных за эту покупку | без `amount` и `points` |
| `redeem`   | Оплата баллами. Списание указанного числа баллов (не больше **30 %** суммы чека) | `amount` > 0, `points` > 0 |

### Правила

- Начисленными баллами можно пользоваться сразу.
- Номер чека (`check_number`) уникален среди **покупок**. Повторная покупка с тем же номером отклоняется.
- Покупка и оплата баллами **могут** иметь один и тот же номер чека.
- Возврат ссылается на номер чека покупки.
- Баланс может стать **отрицательным** (если баллы уже потратили, а потом сделали возврат). Следующие начисления сначала погашают долг.
- Баллы за покупку начисляются на **всю** сумму чека, независимо от оплаты баллами.

### Формат операции (JSON)

```json
{
  "operation_id": "S12-K03-000154",
  "type": "purchase",
  "customer_id": "C1042",
  "store_id": "S12",
  "check_number": "S12-000154",
  "amount": "2490.00",
  "occurred_at": "2026-11-10T14:32:05+07:00"
}
```

Обязательные для всех: `operation_id`, `type`, `customer_id`, `store_id`, `check_number`, `occurred_at`.  
`amount` — только для purchase/redeem.  
`points` — только для redeem.

---

## Микросервисы

### api

**Роль:** точка входа. Принимает операции касс, публикует их в очередь, отдаёт результаты и балансы.

- Стек: FastAPI + aio-pika + SQLAlchemy (asyncpg)
- **Не считает** баллы и **не меняет** баланс
- Проверяет только формат (Pydantic) → при ошибке `422`, при успехе `202`
- Публикация с `delivery_mode=2`, `message_id`, publisher confirms; если брокер не подтвердил — `503`
- Читает данные из PostgreSQL

### worker

**Роль:** единственный, кто применяет бизнес-логику.

- Стек: aio-pika + SQLAlchemy (asyncpg), **без** веб-фреймворка
- `connect_robust`, `prefetch_count=1` (обрабатывает по одному сообщению)
- В **одной транзакции**: блокировка счёта (`SELECT … FOR UPDATE`), расчёт, запись операции, обновление баланса
- Идемпотентность: повторная доставка того же `operation_id` не применяет операцию второй раз
- После фиксации транзакции публикует событие в fanout-обменник
- Ack сообщения — только после успешной публикации события
- Создаёт таблицы при старте (`metadata.create_all`)

Доменный слой (`domain.py`) **не импортирует** aio-pika и SQLAlchemy.

### notifier

**Роль:** уведомления покупателям.

- Стек: FastAPI + aio-pika
- Данные **только в памяти** (после перезапуска теряются)
- Текст: «Начислено N баллов, баланс M» / «Списано N баллов, баланс M» / «Операция отклонена: …»
- Имитация отправки: случайная задержка `MIN_DELAY_MS`–`MAX_DELAY_MS`
- Покупатели из `UNSUBSCRIBED` не получают уведомления (событие при этом считается полученным)
- Маршруты: `GET /notifications?customer_id=…`, `GET /stats`

### analytics

**Роль:** статистика по магазинам.

- Стек: FastAPI + aio-pika
- Данные **только в памяти**
- По каждому магазину: число принятых purchase/return/redeem, число rejected, суммы начисленных / возвращённых / потраченных баллов
- Суммы хранятся неотрицательными (`abs(points_delta)` для return и redeem)
- Маршруты: `GET /stores`, `GET /stores/{store_id}`, `GET /stats`

---

## Поток данных

1. Касса → `POST /operations` в **api**
2. api проверяет формат → публикует в exchange `loyalty` (routing key `operation`)
3. Сообщение попадает в queue `operations`
4. **worker** забирает сообщение:
   - проверяет, не обработано ли уже;
   - блокирует счёт покупателя;
   - ищет покупку/возврат по `check_number`;
   - вызывает `apply_operation` (доменный слой);
   - сохраняет результат и обновляет баланс;
   - публикует событие в `loyalty.events` (fanout).
5. Fanout доставляет **копию** события в `notifier.events` и `analytics.events`
6. **notifier** и **analytics** обрабатывают событие независимо

Касса **не ждёт** обработки: api сразу отвечает `202 Accepted`.

---

## RabbitMQ

### Обменники

| Имя              | Тип     | Назначение                                      |
|------------------|---------|-------------------------------------------------|
| `loyalty`        | direct  | Приём операций от api                           |
| `loyalty.events` | fanout  | Широковещательная рассылка событий после обработки |

### Очереди (все quorum, durable)

| Имя                 | Кто читает  | Откуда                          |
|---------------------|-------------|---------------------------------|
| `operations`        | worker      | `loyalty` (key = `operation`)   |
| `notifier.events`   | notifier    | `loyalty.events`                |
| `analytics.events`  | analytics   | `loyalty.events`                |

### Параметры публикации

- `delivery_mode = 2` (persistent)
- `message_id` = `operation_id`
- Publisher confirms включены
- api: `mandatory=True`, таймаут 5 с → при отказе `503`

Worker, notifier и analytics при старте **сами** объявляют нужные exchange/queue/binding, поэтому порядок запуска контейнеров не критичен (кроме того, что api ждёт старта worker, чтобы таблицы уже существовали).

---

## База данных

Две таблицы (создаются worker при старте):

### accounts
| Колонка       | Тип     | Описание              |
|---------------|---------|-----------------------|
| customer_id   | String  | PK, ID покупателя     |
| balance       | Integer | Текущий баланс баллов |

Счёт создаётся с балансом `0` при первой операции покупателя.

### operations
| Колонка        | Тип              | Описание                          |
|----------------|------------------|-----------------------------------|
| operation_id   | String           | PK                                |
| type           | String           | purchase / return / redeem        |
| customer_id    | String           |                                   |
| store_id       | String           |                                   |
| check_number   | String           |                                   |
| amount         | Numeric(12, 2)   | сумма чека (может быть NULL)     |
| points_delta   | Integer          | изменение баллов (+/−/0)          |
| balance_after  | Integer          | баланс после операции             |
| status         | String           | `applied` / `rejected`            |
| reject_reason  | String           | причина отказа или NULL           |
| occurred_at    | DateTime(tz)     | время операции с кассы            |
| processed_at   | DateTime(tz)     | время обработки worker            |

Индексы:
- `(customer_id, processed_at)` — для ленты операций в `GET /accounts/…`
- `(check_number, type)` — для поиска покупки при возврате

---

## API

### api (порт 8000)

| Метод | Путь                         | Описание                                      | Коды        |
|-------|------------------------------|-----------------------------------------------|-------------|
| POST  | `/operations`                | Приём операции                                | 202, 422, 503 |
| GET   | `/operations/{operation_id}` | Результат обработки                           | 200, 404    |
| GET   | `/accounts/{customer_id}`    | Баланс + до 20 последних операций (новые сверху) | 200, 404 |
| GET   | `/health`                    | Проверка БД и брокера                         | 200, 503    |

**Пример тела POST /operations** — см. раздел «Предметная область».

**Пример ответа GET /operations/{id} (событие):**
```json
{
  "operation_id": "S12-K03-000154",
  "type": "purchase",
  "customer_id": "C1042",
  "store_id": "S12",
  "status": "applied",
  "points_delta": 124,
  "balance_after": 124,
  "reject_reason": null,
  "processed_at": "2026-11-10T07:32:06+00:00"
}
```

### notifier (порт 8001)

| Метод | Путь                          | Описание                                      |
|-------|-------------------------------|-----------------------------------------------|
| GET   | `/notifications?customer_id=` | Список уведомлений покупателя (массив)        |
| GET   | `/stats`                      | `events_received`, `notifications_sent`       |

### analytics (порт 8002)

| Метод | Путь                | Описание                                      |
|-------|---------------------|-----------------------------------------------|
| GET   | `/stores`           | Статистика по всем магазинам                  |
| GET   | `/stores/{store_id}`| Статистика одного магазина (404, если нет)    |
| GET   | `/stats`            | `events_received`                             |

**Поля статистики магазина:**
```json
{
  "store_id": "S12",
  "purchases_applied": 2,
  "returns_applied": 1,
  "redeems_applied": 1,
  "rejected": 3,
  "points_accrued": 324,
  "points_returned": 124,
  "points_redeemed": 100
}
```

---

## Конфигурация

| Переменная              | Сервисы           | По умолчанию     | Назначение                          |
|-------------------------|-------------------|------------------|-------------------------------------|
| `DATABASE_URL`          | api, worker       | из compose       | `postgresql+asyncpg://…`            |
| `RABBITMQ_URL`          | все               | из compose       | `amqp://…`                          |
| `MIN_DELAY_MS`          | notifier          | 200              | мин. задержка «отправки», мс        |
| `MAX_DELAY_MS`          | notifier          | 1500             | макс. задержка «отправки», мс       |
| `UNSUBSCRIBED`          | notifier          | пусто            | ID покупателей через запятую        |
| `POSTGRES_USER`         | postgres          | loyalty          |                                     |
| `POSTGRES_PASSWORD`     | postgres          | loyalty_pass     |                                     |
| `POSTGRES_DB`           | postgres          | loyalty          |                                     |
| `RABBITMQ_DEFAULT_USER` | rabbitmq          | loyalty          |                                     |
| `RABBITMQ_DEFAULT_PASS` | rabbitmq          | loyalty_pass     |                                     |

В `docker-compose.yml` URL собираются из этих переменных через якоря YAML.

---

## Запуск

### Требования
- Docker + Docker Compose
- Свободные порты: 8000, 8001, 8002, 15672

### Команды

```bash
# Сборка и запуск всех сервисов
docker compose up --build

# В фоне
docker compose up --build -d

# Логи конкретного сервиса
docker compose logs -f worker
docker compose logs -f api

# Остановка (данные в томах сохраняются)
docker compose down

# Полная очистка (тома тоже)
docker compose down -v
```

После старта:
- api:        http://localhost:8000
- notifier:   http://localhost:8001
- analytics:  http://localhost:8002
- RabbitMQ UI: http://localhost:15672  (login/pass: `loyalty` / `loyalty_pass`)

Порядок зависимостей:
1. postgres и rabbitmq должны стать **healthy**
2. worker стартует после них (создаёт таблицы)
3. api стартует после worker (`service_started`)
4. notifier и analytics — после rabbitmq

---

## Проверка работоспособности

### 1. Health

```bash
curl http://localhost:8000/health
# {"database":"ok","broker":"ok"}
```

### 2. Покупка (начисление 5 %)

```bash
curl -s -X POST http://localhost:8000/operations \
  -H "Content-Type: application/json" \
  -d '{
    "operation_id": "S12-K03-000154",
    "type": "purchase",
    "customer_id": "C1042",
    "store_id": "S12",
    "check_number": "S12-000154",
    "amount": "2490.00",
    "occurred_at": "2026-11-10T14:32:05+07:00"
  }'
# 202 {"operation_id":"S12-K03-000154"}
```

2490 × 0.05 = 124.5 → **124** балла (дробь отброшена).

### 3. Результат и счёт

```bash
curl -s http://localhost:8000/operations/S12-K03-000154 | jq
curl -s http://localhost:8000/accounts/C1042 | jq
```

### 4. Оплата баллами (лимит 30 %)

```bash
# 500 баллов при чеке 1000 ₽ → limit_exceeded (лимит 300)
curl -s -X POST http://localhost:8000/operations \
  -H "Content-Type: application/json" \
  -d '{
    "operation_id": "S12-K03-000155",
    "type": "redeem",
    "customer_id": "C1042",
    "store_id": "S12",
    "check_number": "S12-000155",
    "amount": "1000.00",
    "points": 500,
    "occurred_at": "2026-11-10T14:35:00+07:00"
  }'
```

### 5. Уведомления и статистика

```bash
curl -s "http://localhost:8001/notifications?customer_id=C1042" | jq
curl -s http://localhost:8001/stats | jq

curl -s http://localhost:8002/stores | jq
curl -s http://localhost:8002/stats | jq
```

### 6. Панель RabbitMQ

http://localhost:15672 → Exchanges / Queues  
Должны быть видны `loyalty`, `loyalty.events`, `operations`, `notifier.events`, `analytics.events`.

### 7. Ошибка формата (422)

```bash
# redeem без points
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/operations \
  -H "Content-Type: application/json" \
  -d '{
    "operation_id": "bad-1",
    "type": "redeem",
    "customer_id": "C1042",
    "store_id": "S12",
    "check_number": "X",
    "amount": "100.00",
    "occurred_at": "2026-11-10T14:00:00+07:00"
  }'
# 422
```

---

## Структура репозитория

```
.
├── docker-compose.yml
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py          # FastAPI-приложение
│   ├── schemas.py       # Pydantic-модели (валидация)
│   └── tables.py        # описание таблиц для чтения
├── worker/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py          # потребитель очереди + публикация событий
│   ├── domain.py        # чистая бизнес-логика (без I/O)
│   └── db.py            # SQLAlchemy Core, таблицы, запросы
├── notifier/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
└── analytics/
    ├── Dockerfile
    ├── requirements.txt
    └── main.py
```

Все Dockerfile — **многостадийная сборка**, запуск от непривилегированного пользователя `appuser` (uid 1000).

---

## Причины отклонения операций

Порядок проверок важен: при нескольких подходящих причинах указывается **первая** по таблице.

| reject_reason          | Операция | Условие                                      |
|------------------------|----------|----------------------------------------------|
| `duplicate_purchase`   | purchase | Покупка с таким `check_number` уже accepted  |
| `purchase_not_found`   | return   | Нет принятой покупки с этим номером чека     |
| `customer_mismatch`    | return   | Покупка оформлена на другого покупателя      |
| `already_returned`     | return   | По этой покупке уже был возврат              |
| `limit_exceeded`       | redeem   | `points` > 30 % от `amount`                  |
| `insufficient_balance` | redeem   | `points` > текущего баланса                  |

Для принятых операций `reject_reason = null`, `points_delta` может быть > 0, < 0 или 0 (для rejected всегда 0).

---

## Ключевые технические решения

1. **Асинхронность** — api не блокируется на обработке; касса получает 202 сразу.
2. **Одна транзакция в worker** — расчёт + запись операции + баланс атомарны.
3. **SELECT FOR UPDATE** — защита от гонок по балансу одного покупателя.
4. **Идемпотентность** — повторная доставка сообщения не дублирует эффект.
5. **Quorum-очереди** — устойчивость данных брокера.
6. **Fanout** — notifier и analytics независимы; остановка одного не мешает другому.
7. **Объявление топологии в каждом сервисе** — можно запускать в любом порядке.
8. **Доменный слой без инфраструктуры** — `domain.py` легко тестировать отдельно.

---

## Полезные команды Docker

```bash
# Статус
docker compose ps

# Перезапуск одного сервиса
docker compose restart worker

# Зайти в логи с начала
docker compose logs --no-log-prefix worker | head -50

# Проверка очередей через rabbitmqctl (внутри контейнера)
docker compose exec rabbitmq rabbitmqctl list_queues name messages
docker compose exec rabbitmq rabbitmqctl list_exchanges name type
```
