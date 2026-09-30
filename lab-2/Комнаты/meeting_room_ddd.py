from dataclasses import dataclass
from datetime import datetime, time
from typing import Protocol


# Доменные исключения
  # Родитель всех доменных ошибок
class DomainError(Exception):
    pass

# Объекту-значению передали неправильные данные
class InvalidValueObject(DomainError):  
    pass

# Операция нарушает правило предметной области
class DomainInvariantViolation(DomainError):
    pass

 # Нужная комната или бронирование не найдены
class EntityNotFound(DomainError):
    pass


# объекты-значения

    # общая проверка для идентификаторов: целое число больше 0
def _check_positive_id(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise InvalidValueObject(f"{label} должен быть положительным целым числом")

# идентификатор переговорной комнаты
@dataclass(frozen=True)
class RoomId:
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID комнаты")

# идентификатор сотрудника
@dataclass(frozen=True)
class EmployeeId:
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID сотрудника")

# идентификатор бронирования
@dataclass(frozen=True)
class BookingId:
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID бронирования")

# максимальное количество людей в комнате
@dataclass(frozen=True)
class Capacity:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value <= 0:
            raise InvalidValueObject("Вместимость должна быть положительным целым числом")

# количество участников встречи
@dataclass(frozen=True)
class ParticipantCount:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value <= 0:
            raise InvalidValueObject("Количество участников должно быть больше 0")

# часы работы офиса
@dataclass(frozen=True)
class OfficeHours:
    start: time
    end: time

    def __post_init__(self) -> None:
        if type(self.start) is not time or type(self.end) is not time:
            raise InvalidValueObject("Часы работы должны иметь тип time")
        if self.end <= self.start:
            raise InvalidValueObject("Время окончания работы должно быть позже начала")

# интервал бронирования
@dataclass(frozen=True)
class BookingPeriod:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if type(self.start) is not datetime or type(self.end) is not datetime:
            raise InvalidValueObject("Начало и конец бронирования должны иметь тип datetime")

        # начало бронирования должно быть раньше конца
        if self.end <= self.start:
            raise InvalidValueObject("Окончание бронирования должно быть позже начала")

        # бронь должна быть в пределах одного дня
        if self.start.date() != self.end.date():
            raise InvalidValueObject("Бронирование должно начинаться и заканчиваться в один день")


# 1 агрегат - переговорная комната (MeetingRoom)
# отвечает за вместимость комнаты и рабочие часы
class MeetingRoom:
    def __init__(
        self,
        room_id: RoomId,
        name: str,
        capacity: Capacity,
        office_hours: OfficeHours,
    ) -> None:
        if not isinstance(room_id, RoomId):
            raise InvalidValueObject("Нужен корректный RoomId")
        if not isinstance(name, str) or not name.strip():
            raise InvalidValueObject("Название комнаты не может быть пустым")
        if not isinstance(capacity, Capacity):
            raise InvalidValueObject("Нужна корректная вместимость")
        if not isinstance(office_hours, OfficeHours):
            raise InvalidValueObject("Нужны корректные часы работы")

        self._id = room_id
        self._name = name.strip()
        self._capacity = capacity
        self._office_hours = office_hours

    # свойства дают читать данные, но не менять их напрямую
    @property
    def id(self) -> RoomId:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def capacity(self) -> Capacity:
        return self._capacity

    @property
    def office_hours(self) -> OfficeHours:
        return self._office_hours

    def validate_booking(self, period: BookingPeriod, participants: ParticipantCount) -> None:
        # проверяем правила комнаты перед созданием бронирования
        if not isinstance(period, BookingPeriod) or not isinstance(participants, ParticipantCount):
            raise InvalidValueObject("Некорректные данные бронирования")

        # инвариант 1 - участников не может быть больше вместимости комнаты
        if participants.value > self._capacity.value:
            raise DomainInvariantViolation("Количество участников превышает вместимость комнаты")

        # инвариант 2 - бронь не может начинаться раньше открытия офиса
        if period.start.time() < self._office_hours.start:
            raise DomainInvariantViolation("Бронирование начинается раньше открытия офиса")

        # инвариант 3 - бронь не может заканчиваться позже закрытия офиса
        if period.end.time() > self._office_hours.end:
            raise DomainInvariantViolation("Бронирование заканчивается позже закрытия офиса")

    def snapshot(self) -> dict:
        # сохраняем состояние комнаты в обычный словарь
        return {
            "room_id": self._id.value,
            "name": self._name,
            "capacity": self._capacity.value,
            "office_start": self._office_hours.start.isoformat(),
            "office_end": self._office_hours.end.isoformat(),
        }


# 2 агрегат - бронирование (Booking)
# хранит данные конкретной брони
class Booking:
    def __init__(
        self,
        booking_id: BookingId,
        room_id: RoomId,
        employee_id: EmployeeId,
        period: BookingPeriod,
        participants: ParticipantCount,
    ) -> None:
        if not (
            isinstance(booking_id, BookingId)
            and isinstance(room_id, RoomId)
            and isinstance(employee_id, EmployeeId)
            and isinstance(period, BookingPeriod)
            and isinstance(participants, ParticipantCount)
        ):
            raise InvalidValueObject("Некорректные данные бронирования")

        self._id = booking_id
        self._room_id = room_id
        self._employee_id = employee_id
        self._period = period
        self._participants = participants
        self._status = "active"

    @property
    def id(self) -> BookingId:
        return self._id

    @property
    def room_id(self) -> RoomId:
        return self._room_id

    @property
    def period(self) -> BookingPeriod:
        return self._period

    @property
    def status(self) -> str:
        return self._status

    def overlaps(self, other_period: BookingPeriod) -> bool:
        # проверяем пересекается ли эта бронь с другим интервалом
        # если одна бронь закончилась ровно в момент начала другой - пересечения нет
        return (
            self._period.start < other_period.end
            and other_period.start < self._period.end
        )

    def snapshot(self) -> dict:
        # сохраняем бронирование в словарь
        return {
            "booking_id": self._id.value,
            "room_id": self._room_id.value,
            "employee_id": self._employee_id.value,
            "start": self._period.start.isoformat(),
            "end": self._period.end.isoformat(),
            "participants": self._participants.value,
            "status": self._status,
        }


# фабрики восстановления

def _saved_datetime(raw: str) -> datetime:
    # сохраненную строку обратно в datetime
    if not isinstance(raw, str):
        raise InvalidValueObject("Сохраненная дата должна быть строкой")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidValueObject("Некорректная дата в сохраненных данных") from exc


def _saved_time(raw: str) -> time:
    # сохраненное время обратно в time
    if not isinstance(raw, str):
        raise InvalidValueObject("Сохраненное время должно быть строкой")
    try:
        return time.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidValueObject("Некорректное время в сохраненных данных") from exc


class MeetingRoomFactory:
    # восстановление комнат и проверяка вместимость и часы работы
    @staticmethod
    def restore(data: dict) -> MeetingRoom:
        return MeetingRoom(
            RoomId(data["room_id"]),
            data["name"],
            Capacity(data["capacity"]),
            OfficeHours(
                _saved_time(data["office_start"]),
                _saved_time(data["office_end"]),
            ),
        )


class BookingFactory:
    # восстановление бронирования и проверка всех объектов-значений
    @staticmethod
    def restore(data: dict) -> Booking:
        booking = Booking(
            BookingId(data["booking_id"]),
            RoomId(data["room_id"]),
            EmployeeId(data["employee_id"]),
            BookingPeriod(
                _saved_datetime(data["start"]),
                _saved_datetime(data["end"]),
            ),
            ParticipantCount(data["participants"]),
        )

        # только активный статус
        if data["status"] != "active":
            raise DomainInvariantViolation("Неизвестный статус бронирования")

        return booking


# порты репозиториев

class RoomRepository(Protocol):
    def get(self, room_id: RoomId) -> MeetingRoom: ...
    def save(self, room: MeetingRoom) -> None: ...


class BookingRepository(Protocol):
    def get(self, booking_id: BookingId) -> Booking: ...
    def add(self, booking: Booking) -> None: ...
    def list_by_room(self, room_id: RoomId) -> list[Booking]: ...


# доменный сервис
# создание брони затрагивает и комнату и уже существующие бронирования
class BookingService:
    def __init__(self, rooms: RoomRepository, bookings: BookingRepository) -> None:
        self._rooms = rooms
        self._bookings = bookings

    def create_booking(
        self,
        booking_id: BookingId,
        room_id: RoomId,
        employee_id: EmployeeId,
        period: BookingPeriod,
        participants: ParticipantCount,
    ) -> Booking:
        # находим нужную комнату
        room = self._rooms.get(room_id)

        # комната сама проверяет вместимость и рабочие часы
        room.validate_booking(period, participants)

        # инвариант 4 - брони одной комнаты не должны пересекаться
        for existing in self._bookings.list_by_room(room_id):
            if existing.overlaps(period):
                raise DomainInvariantViolation("На это время комната уже забронирована")

        # если все проверки пройдены создаем бронь
        booking = Booking(
            booking_id,
            room_id,
            employee_id,
            period,
            participants,
        )

        self._bookings.add(booking)
        return booking


# хранилища в памяти - обычные словари Python
class InMemoryRoomRepository:
    def __init__(self) -> None:
        self._data: dict[int, dict] = {}

    def get(self, room_id: RoomId) -> MeetingRoom:
        if room_id.value not in self._data:
            raise EntityNotFound("Переговорная комната не найдена")
        return MeetingRoomFactory.restore(self._data[room_id.value].copy())

    def save(self, room: MeetingRoom) -> None:
        self._data[room.id.value] = room.snapshot()


class InMemoryBookingRepository:
    def __init__(self) -> None:
        self._data: dict[int, dict] = {}

    def get(self, booking_id: BookingId) -> Booking:
        if booking_id.value not in self._data:
            raise EntityNotFound("Бронирование не найдено")
        return BookingFactory.restore(self._data[booking_id.value].copy())

    def add(self, booking: Booking) -> None:
        # два бронирования не могут иметь одинаковый ID
        if booking.id.value in self._data:
            raise DomainInvariantViolation("ID бронирования уже используется")
        self._data[booking.id.value] = booking.snapshot()

    def list_by_room(self, room_id: RoomId) -> list[Booking]:
        # возвращаем все бронирования нужной комнаты
        result = []
        for data in self._data.values():
            if data["room_id"] == room_id.value:
                result.append(BookingFactory.restore(data.copy()))
        return result
