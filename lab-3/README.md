# Лабораторные работы №2 и №3  
Дисциплина «Разработка программных приложений»  
Предметная область: «Бронирование переговорных комнат»

Учебный проект по DDD и паттерну «Состояние» (GoF).

## Что внутри

**ЛР2 — доменная модель по DDD:**
- два агрегата: `MeetingRoom`, `Booking`;
- объекты-значения (`frozen dataclass` с валидацией в `__post_init__`):
  `RoomId`, `EmployeeId`, `BookingId`, `Capacity`, `ParticipantCount`,
  `OfficeHours`, `BookingPeriod`;
- инварианты: вместимость, рабочие часы, запрет пересечения броней,
  24 часа на согласование, 15 минут на отметку, три неявки;
- доменный сервис `BookingAvailabilityService` (трогает > 1 агрегата);
- связь между агрегатами только по `RoomId`;
- репозитории — `Protocol` + in-memory реализации;
- своя иерархия исключений.

**ЛР3, разделы I–III — жизненный цикл и State pattern:**
- `BookingState` + конкретные состояния, базовый класс запрещает всё
  по умолчанию, `TransitionNotAllowed` на недопустимый переход;
- состояние меняется только через методы-события, сеттера нет;
- прикладной сервис `BookingProcess`: каждая задача схемы — отдельный
  метод, каждый шлюз — именованный предикат, `GatewayUnresolved` при
  непокрытом случае;
- журнал доменных событий в агрегате, `pull_events()` наружу;
- порт `Clock` и адаптер `SystemClock` — `datetime.now()` только там.

## Структура

```
.
├── meeting_room_ddd.py       # домен
├── booking_process.py        # прикладной сервис
├── adapters.py               # SystemClock
├── test_booking_process.py   # тесты
└── README.md
```

## Запуск

Тесты:

```bash
python -m unittest -v test_booking_process.py
```

Ожидаемый результат — `OK`, все тесты зелёные.

## Быстрый ручной прогон

```python
from datetime import datetime, time, timedelta
from adapters import SystemClock
from booking_process import BookingProcess
from meeting_room_ddd import (
    BookingId, BookingPeriod, Capacity, EmployeeId,
    InMemoryBookingRepository, InMemoryRoomRepository, MeetingRoom,
    OfficeHours, ParticipantCount, RoomId,
)

rooms = InMemoryRoomRepository()
bookings = InMemoryBookingRepository()
process = BookingProcess(rooms, bookings, SystemClock())

rooms.save(MeetingRoom(
    RoomId(1), "Переговорная 1",
    Capacity(10), OfficeHours(time(9, 0), time(18, 0)),
))

start = datetime(2026, 10, 20, 10, 0)
process.create_booking_request(
    BookingId(1), RoomId(1), EmployeeId(1),
    BookingPeriod(start, start + timedelta(hours=1)),
    ParticipantCount(5),
)
booking = process.process_initial_checks(
    BookingId(1), datetime(2026, 10, 19, 12, 0)
)
print(booking.state)          # under_approval
print(process.pull_events())  # [ApprovalRequested(...)]
```

## Слои

| Слой | Файл | Что лежит |
|---|---|---|
| Домен | `meeting_room_ddd.py` | агрегаты, VO, события, доменный сервис, порты репозиториев |
| Прикладной | `booking_process.py` | сценарии, шлюзы, публикация событий |
| Адаптеры | `adapters.py` | `SystemClock` (позже — Flask, in-memory заглушки) |

## Соответствие требованиям

| Требование | Где |
|---|---|
| Два агрегата | `MeetingRoom`, `Booking` |
| Нетривиальные инварианты | `MeetingRoom.validate_booking`, правила в `BookingState` |
| VO с валидацией | `RoomId`, `Capacity`, `BookingPeriod`, … |
| Связь только по ID | `Booking.room_id: RoomId` |
| Доменный сервис | `BookingAvailabilityService` |
| Домен без инфраструктуры | `meeting_room_ddd.py` |
| Смена состояния только через методы | приватный `_state`, только event-методы |
| Репозитории как Protocol | `RoomRepository`, `BookingRepository` |
| in-memory БД | `InMemoryRoomRepository`, `InMemoryBookingRepository` |
| Иерархия исключений | `DomainError` и потомки |
| Паттерн «Состояние» | иерархия `BookingState` |
| Журнал доменных событий | `Booking._events`, `pull_events()` |
| Порт `Clock` | `meeting_room_ddd.Clock`, `adapters.SystemClock` |
| `GatewayUnresolved` | `booking_process.BookingProcess` |