# Доменный слой

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Protocol

# Доменные исключения

class DomainError(Exception):
    pass

# когда объекту-значению дали некорректные данные
class InvalidValueObject(DomainError):
    pass

# Нарушено бизнес-правило, но данные сами по себе корректные
class DomainInvariantViolation(DomainError):
    pass

# Репозиторий не нашёл нужную сущность
class EntityNotFound(DomainError):
    pass

# Событие недопустимо в текущем состоянии
class TransitionNotAllowed(DomainError):
    def __init__(self, state: str, event: str) -> None:
        self.state = state
        self.event = event
        super().__init__(
            f"Переход недопустим: состояние='{state}', событие='{event}'"
        )

# Ни одна ветвь исключающего шлюза не сработала 
class GatewayUnresolved(DomainError):
    pass

# Порт часов чтобы домен и прикладной слой не звали datetime.now()
class Clock(Protocol):
    def now(self) -> datetime: ...

# Объекты-значения 
def _check_positive_id(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise InvalidValueObject(f"{label} должен быть положительным целым числом")

@dataclass(frozen=True)
class RoomId:
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID комнаты")

@dataclass(frozen=True)
class EmployeeId:
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID сотрудника")

@dataclass(frozen=True)
class BookingId:
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID бронирования")

@dataclass(frozen=True)
class Capacity:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value <= 0:
            raise InvalidValueObject(
                "Вместимость должна быть положительным целым числом"
            )

@dataclass(frozen=True)
class ParticipantCount:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value <= 0:
            raise InvalidValueObject("Количество участников должно быть больше 0")

@dataclass(frozen=True)
class OfficeHours:
    start: time
    end: time

    def __post_init__(self) -> None:
        if type(self.start) is not time or type(self.end) is not time:
            raise InvalidValueObject("Часы работы должны иметь тип time")
        if self.end <= self.start:
            raise InvalidValueObject(
                "Время окончания работы должно быть позже начала"
            )

@dataclass(frozen=True)
class BookingPeriod:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if type(self.start) is not datetime or type(self.end) is not datetime:
            raise InvalidValueObject(
                "Начало и конец бронирования должны иметь тип datetime"
            )
        if self.end <= self.start:
            raise InvalidValueObject(
                "Окончание бронирования должно быть позже начала"
            )
        if self.start.date() != self.end.date():
            raise InvalidValueObject(
                "Бронирование должно начинаться и заканчиваться в один день"
            )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

# Доменные события-сообщения

@dataclass(frozen=True)
class ApprovalRequested:
    booking_id: BookingId
    employee_id: EmployeeId
    requested_at: datetime

@dataclass(frozen=True)
class AdminOrderRequested:
    booking_id: BookingId
    employee_id: EmployeeId
    equipment: bool
    catering: bool

@dataclass(frozen=True)
class BookingRejected:
    booking_id: BookingId
    reason: str

@dataclass(frozen=True)
class BookingApproved:
    booking_id: BookingId

@dataclass(frozen=True)
class BookingRejectedByManager:
    booking_id: BookingId

@dataclass(frozen=True)
class ApprovalTimeoutExpired:
    booking_id: BookingId
    occurred_at: datetime

@dataclass(frozen=True)
class RoomConfirmed:
    booking_id: BookingId

@dataclass(frozen=True)
class AdminOrderConfirmed:
    booking_id: BookingId

@dataclass(frozen=True)
class BookingCancelled:
    booking_id: BookingId
    occurred_at: datetime

@dataclass(frozen=True)
class MeetingStarted:
    booking_id: BookingId
    occurred_at: datetime

@dataclass(frozen=True)
class CheckedIn:
    booking_id: BookingId
    occurred_at: datetime

@dataclass(frozen=True)
class NoShowRecorded:
    booking_id: BookingId
    occurred_at: datetime

# Агрегат MeetingRoom корень агрегата комната.
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

    # Хватает ли мест под заявленное число участников
    def has_enough_capacity(self, participants: ParticipantCount) -> bool:
        return participants.value <= self._capacity.value

    # Попадает ли интервал целиком в рабочие часы комнаты
    def is_within_office_hours(self, period: BookingPeriod) -> bool:
        return (
            period.start.time() >= self._office_hours.start
            and period.end.time() <= self._office_hours.end
        )

    # Единая точка проверки инвариантов ЛР2 используется фабрикой/сервисом.
    def validate_booking(
        self, period: BookingPeriod, participants: ParticipantCount
    ) -> None:
        if not isinstance(period, BookingPeriod) or not isinstance(
            participants, ParticipantCount
        ):
            raise InvalidValueObject("Некорректные данные бронирования")

        if not self.has_enough_capacity(participants):
            raise DomainInvariantViolation(
                "Количество участников превышает вместимость комнаты"
            )
        if not self.is_within_office_hours(period):
            raise DomainInvariantViolation(
                "Бронирование находится за пределами часов работы офиса"
            )

    # Снимок для in-memory репозитория возвращаем примитивы
    def snapshot(self) -> dict:
        return {
            "room_id": self._id.value,
            "name": self._name,
            "capacity": self._capacity.value,
            "office_start": self._office_hours.start.isoformat(),
            "office_end": self._office_hours.end.isoformat(),
        }


# Паттерн «Состояние». Базовый класс запрещает всё по умолчанию

class BookingState:
    name = "base"
    is_final = False

    # Универсальный «отказ»
    def _not_allowed(self, event: str) -> None:
        raise TransitionNotAllowed(self.name, event)

    # Полный список событий из таблицы переходов. Ничего не пропущено любое новое событие автоматом будет запрещено во всех состояниях,

    def reject(self, booking: "Booking", reason: str) -> "BookingState":
        self._not_allowed("reject")

    def request_approval(
        self, booking: "Booking", requested_at: datetime
    ) -> "BookingState":
        self._not_allowed("request_approval")

    def skip_approval(self, booking: "Booking") -> "BookingState":
        self._not_allowed("skip_approval")

    def approve(self, booking: "Booking") -> "BookingState":
        self._not_allowed("approve")

    def reject_by_manager(self, booking: "Booking") -> "BookingState":
        self._not_allowed("reject_by_manager")

    def on_approval_timeout(
        self, booking: "Booking", now: datetime
    ) -> "BookingState":
        self._not_allowed("on_approval_timeout")

    def confirm_room(self, booking: "Booking") -> "BookingState":
        self._not_allowed("confirm_room")

    def confirm_admin_order(self, booking: "Booking") -> "BookingState":
        self._not_allowed("confirm_admin_order")

    def cancel(self, booking: "Booking", now: datetime) -> "BookingState":
        self._not_allowed("cancel")

    def on_meeting_start(
        self, booking: "Booking", now: datetime
    ) -> "BookingState":
        self._not_allowed("on_meeting_start")

    def check_in(self, booking: "Booking", now: datetime) -> "BookingState":
        self._not_allowed("check_in")

    def on_check_in_timeout(
        self, booking: "Booking", now: datetime
    ) -> "BookingState":
        self._not_allowed("on_check_in_timeout")


# Заявка только что создана: отклонить, отправить на согласование или сразу пропустить согласование 
# (мелкая комната, короткая встреча).
class SubmittedState(BookingState):
    name = "submitted"

    def reject(self, booking: "Booking", reason: str) -> BookingState:
        # Причину сохраняем в агрегат, чтобы её можно было показать пользователю
        if not isinstance(reason, str) or not reason.strip():
            raise DomainInvariantViolation("Причина отклонения не может быть пустой")
        booking._rejection_reason = reason.strip()
        return RejectedState()

    def request_approval(
        self, booking: "Booking", requested_at: datetime
    ) -> BookingState:
        if not isinstance(requested_at, datetime):
            raise InvalidValueObject("Время запроса согласования должно быть datetime")
        # Запоминаем момент запроса от него потом считаем 24 часа.
        booking._approval_requested_at = requested_at
        return UnderApprovalState()

    def skip_approval(self, booking: "Booking") -> BookingState:
        return PreparingState()


# Ждём ответа руководителя. Разрешены: согласовать, отклонить, таймаут.
class UnderApprovalState(BookingState):
    name = "under_approval"

    def approve(self, booking: "Booking") -> BookingState:
        return PreparingState()

    def reject_by_manager(self, booking: "Booking") -> BookingState:
        booking._rejection_reason = "Заявка отклонена руководителем"
        return RejectedState()

    def on_approval_timeout(
        self, booking: "Booking", now: datetime
    ) -> BookingState:
        if not isinstance(now, datetime):
            raise InvalidValueObject("Текущее время должно быть datetime")
        if booking._approval_requested_at is None:
            raise DomainInvariantViolation(
                "Не зафиксировано время запроса согласования"
            )
        deadline = booking._approval_requested_at + timedelta(hours=24)
        if now < deadline:
            raise DomainInvariantViolation("24 часа на согласование ещё не истекли")
        booking._rejection_reason = "Истёк срок согласования 24 часа"
        return RejectedState()


#  ждём подтверждения комнаты и (если нужно) админ-заказа
class PreparingState(BookingState):
    name = "preparing"

    def _next_state(self, booking: "Booking") -> BookingState:
        if booking._room_confirmed and (
            not booking.requires_admin_order or booking._admin_order_confirmed
        ):
            return ReadyState()
        return PreparingState()

    def confirm_room(self, booking: "Booking") -> BookingState:
        booking._room_confirmed = True
        return self._next_state(booking)

    def confirm_admin_order(self, booking: "Booking") -> BookingState:
        if not booking.requires_admin_order:
            raise DomainInvariantViolation(
                "Для этого бронирования заказ администратора не требуется"
            )
        booking._admin_order_confirmed = True
        return self._next_state(booking)


# Готовая бронь которую можно отменить (до начала) или начать встречу
class ReadyState(BookingState):
    name = "ready"

    def cancel(self, booking: "Booking", now: datetime) -> BookingState:
        if not isinstance(now, datetime):
            raise InvalidValueObject("Текущее время должно быть datetime")
        # Отменять можно только строго до старта встречи
        if now >= booking.period.start:
            raise DomainInvariantViolation(
                "Бронь можно отменить только до начала встречи"
            )
        return CancelledState()

    def on_meeting_start(
        self, booking: "Booking", now: datetime
    ) -> BookingState:
        if not isinstance(now, datetime):
            raise InvalidValueObject("Текущее время должно быть datetime")
        if now < booking.period.start:
            raise DomainInvariantViolation("Время начала встречи ещё не наступило")
        return AwaitingCheckInState()


# Встреча началась, но сотрудник ещё не отметился дается 15 минут
class AwaitingCheckInState(BookingState):
    name = "awaiting_check_in"

    def check_in(self, booking: "Booking", now: datetime) -> BookingState:
        if not isinstance(now, datetime):
            raise InvalidValueObject("Текущее время должно быть datetime")
        deadline = booking.period.start + timedelta(minutes=15)
        if now < booking.period.start:
            raise DomainInvariantViolation("Встреча ещё не началась")
        if now > deadline:
            raise DomainInvariantViolation("Срок отметки 15 минут уже истёк")
        booking._checked_in_at = now
        return HeldState()

    def on_check_in_timeout(
        self, booking: "Booking", now: datetime
    ) -> BookingState:
        if not isinstance(now, datetime):
            raise InvalidValueObject("Текущее время должно быть datetime")
        deadline = booking.period.start + timedelta(minutes=15)
        if now < deadline:
            raise DomainInvariantViolation("15 минут на отметку ещё не истекли")
        booking._no_show_at = now
        return NoShowState()


# Финальные состояния 
class RejectedState(BookingState):
    name = "rejected"
    is_final = True


class CancelledState(BookingState):
    name = "cancelled"
    is_final = True


class NoShowState(BookingState):
    name = "no_show"
    is_final = True


class HeldState(BookingState):
    name = "held"
    is_final = True


# Словарь «имя состояния - класс». Сбор объекта состояния из БД
_STATE_TYPES: dict[str, type[BookingState]] = {
    cls.name: cls
    for cls in (
        SubmittedState,
        UnderApprovalState,
        PreparingState,
        ReadyState,
        AwaitingCheckInState,
        RejectedState,
        CancelledState,
        NoShowState,
        HeldState,
    )
}

# Агрегат Booking корень агрегата.
class Booking:
    def __init__(
        self,
        booking_id: BookingId,
        room_id: RoomId,
        employee_id: EmployeeId,
        period: BookingPeriod,
        participants: ParticipantCount,
        *,
        needs_equipment: bool = False,
        needs_catering: bool = False,
    ) -> None:
        # Всё должно быть объектами-значениями или bool.
        if not (
            isinstance(booking_id, BookingId)
            and isinstance(room_id, RoomId)
            and isinstance(employee_id, EmployeeId)
            and isinstance(period, BookingPeriod)
            and isinstance(participants, ParticipantCount)
        ):
            raise InvalidValueObject("Некорректные данные бронирования")
        if type(needs_equipment) is not bool or type(needs_catering) is not bool:
            raise InvalidValueObject(
                "Признаки оборудования и кейтеринга должны быть bool"
            )

        # Ссылка на комнату через RoomId
        # связь между агрегатами только по идентификатору
        self._id = booking_id
        self._room_id = room_id
        self._employee_id = employee_id
        self._period = period
        self._participants = participants
        self._needs_equipment = needs_equipment
        self._needs_catering = needs_catering

        # Всё приватное, снаружи только методы-события.
        self._state: BookingState = SubmittedState()
        self._approval_requested_at: datetime | None = None
        self._room_confirmed = False
        self._admin_order_confirmed = False
        self._checked_in_at: datetime | None = None
        self._no_show_at: datetime | None = None
        self._rejection_reason: str | None = None

        # Журнал доменных событий чтение извне, пополняется изнутри.
        self._events: list[object] = []

    # Публичные свойства (только чтение)

    @property
    def id(self) -> BookingId:
        return self._id

    @property
    def room_id(self) -> RoomId:
        return self._room_id

    @property
    def employee_id(self) -> EmployeeId:
        return self._employee_id

    @property
    def period(self) -> BookingPeriod:
        return self._period

    @property
    def participants(self) -> ParticipantCount:
        return self._participants

    @property
    def needs_equipment(self) -> bool:
        return self._needs_equipment

    @property
    def needs_catering(self) -> bool:
        return self._needs_catering

    @property
    def requires_admin_order(self) -> bool:
        # Заказ администратору нужен, если попросили оборудование или кейтеринг
        return self._needs_equipment or self._needs_catering

    @property
    def state(self) -> str:
        return self._state.name

    @property
    def is_final(self) -> bool:
        return self._state.is_final

    @property
    def room_confirmed(self) -> bool:
        return self._room_confirmed

    @property
    def admin_order_confirmed(self) -> bool:
        return self._admin_order_confirmed

    @property
    def rejection_reason(self) -> str | None:
        return self._rejection_reason

    @property
    def no_show_at(self) -> datetime | None:
        return self._no_show_at

    @property
    def events(self) -> tuple[object, ...]:
        return tuple(self._events)

    @property
    def blocks_room(self) -> bool:
        # Занимает ли бронь слот. Финальные состояния (rejected, cancelled, No_show, held) слот не занимают
        return self.state in {
            "submitted",
            "under_approval",
            "preparing",
            "ready",
            "awaiting_check_in",
        }

    # Вспомогательные операции

    # Пересечение двух интервалов A.start < B.end и B.start < A.end
    def overlaps(self, other_period: BookingPeriod) -> bool:
        return (
            self._period.start < other_period.end
            and other_period.start < self._period.end
        )

    # Забрать все накопленные события и очистить журнал
    def pull_events(self) -> list[object]:
        events = self._events.copy()
        self._events.clear()
        return events

    def _record(self, event: object) -> None:
        self._events.append(event)

    # Единая точка входа для смены состояния делегируем обработку текущему объекту состояния
    # Если он бросит исключение состояние не поменяется, потому что присваивание не выполнится
    def _apply(self, event: str, *args) -> None:
        handler = getattr(self._state, event)
        self._state = handler(self, *args)

    # Публичные методы-события

    def reject(self, reason: str) -> None:
        self._apply("reject", reason)
        self._record(BookingRejected(self._id, reason))

    def request_approval(self, requested_at: datetime) -> None:
        self._apply("request_approval", requested_at)
        self._record(ApprovalRequested(self._id, self._employee_id, requested_at))

    def skip_approval(self) -> None:
        self._apply("skip_approval")

    def approve(self) -> None:
        self._apply("approve")
        self._record(BookingApproved(self._id))

    def reject_by_manager(self) -> None:
        self._apply("reject_by_manager")
        self._record(BookingRejectedByManager(self._id))

    def on_approval_timeout(self, now: datetime) -> None:
        self._apply("on_approval_timeout", now)
        self._record(ApprovalTimeoutExpired(self._id, now))

    def confirm_room(self) -> None:
        self._apply("confirm_room")
        self._record(RoomConfirmed(self._id))

    def confirm_admin_order(self) -> None:
        self._apply("confirm_admin_order")
        self._record(AdminOrderConfirmed(self._id))

    # Отправка заказа администратору не меняет состояние брони, но это сообщение внешнему участнику оно должно попасть в журнал
    # Поэтому отдельный метод, а не событие состояния
    def note_admin_request(self) -> AdminOrderRequested:
        if not self.requires_admin_order:
            raise DomainInvariantViolation(
                "Для этого бронирования заказ администратора не требуется"
            )
        event = AdminOrderRequested(
            self._id,
            self._employee_id,
            self._needs_equipment,
            self._needs_catering,
        )
        self._record(event)
        return event

    def cancel(self, now: datetime) -> None:
        self._apply("cancel", now)
        self._record(BookingCancelled(self._id, now))

    def on_meeting_start(self, now: datetime) -> None:
        self._apply("on_meeting_start", now)
        self._record(MeetingStarted(self._id, now))

    def check_in(self, now: datetime) -> None:
        self._apply("check_in", now)
        self._record(CheckedIn(self._id, now))

    def on_check_in_timeout(self, now: datetime) -> None:
        self._apply("on_check_in_timeout", now)
        self._record(NoShowRecorded(self._id, now))

    # Служебное

    # Список допустимых событий в текущем состоянии
    def allowed_events(self) -> list[str]:
        mapping = {
            "submitted": ["reject", "request_approval", "skip_approval"],
            "under_approval": [
                "approve",
                "reject_by_manager",
                "on_approval_timeout",
            ],
            "preparing": ["confirm_room", "confirm_admin_order"],
            "ready": ["cancel", "on_meeting_start"],
            "awaiting_check_in": ["check_in", "on_check_in_timeout"],
            "rejected": [],
            "cancelled": [],
            "no_show": [],
            "held": [],
        }
        return mapping[self.state].copy()

    # Снимок для in-memory репозитория События сознательно не сохраняем они живут в рамках одного сценария и выгребаются сервисом сразу
    def snapshot(self) -> dict:
        return {
            "booking_id": self._id.value,
            "room_id": self._room_id.value,
            "employee_id": self._employee_id.value,
            "start": self._period.start.isoformat(),
            "end": self._period.end.isoformat(),
            "participants": self._participants.value,
            "needs_equipment": self._needs_equipment,
            "needs_catering": self._needs_catering,
            "state": self.state,
            "approval_requested_at": (
                self._approval_requested_at.isoformat()
                if self._approval_requested_at
                else None
            ),
            "room_confirmed": self._room_confirmed,
            "admin_order_confirmed": self._admin_order_confirmed,
            "checked_in_at": (
                self._checked_in_at.isoformat() if self._checked_in_at else None
            ),
            "no_show_at": self._no_show_at.isoformat() if self._no_show_at else None,
            "rejection_reason": self._rejection_reason,
        }


# Доменный сервис
# Вынесен отдельно, потому что для проверки доступности затрагивается больше одного агрегата

class BookingAvailabilityService:
    @staticmethod
    def is_available(booking: Booking, existing: list[Booking]) -> bool:
        for other in existing:
            # Свою же бронь не считаем конфликтом
            if other.id == booking.id:
                continue
            if other.blocks_room and other.overlaps(booking.period):
                return False
        return True


# Фабрики восстановления. Нужны, чтобы репозиторий отдавал объект а не словарь. Заодно перепроверяют согласованность состояния.

def _saved_datetime(raw: str) -> datetime:
    if not isinstance(raw, str):
        raise InvalidValueObject("Сохраненная дата должна быть строкой")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidValueObject("Некорректная дата в сохраненных данных") from exc


def _saved_optional_datetime(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    return _saved_datetime(raw)


def _saved_time(raw: str) -> time:
    if not isinstance(raw, str):
        raise InvalidValueObject("Сохраненное время должно быть строкой")
    try:
        return time.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidValueObject("Некорректное время в сохраненных данных") from exc


class MeetingRoomFactory:
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
            needs_equipment=data.get("needs_equipment", False),
            needs_catering=data.get("needs_catering", False),
        )

        # Восстанавливаем состояние находим класс по имени и создаём
        state_name = data.get("state", "submitted")
        state_type = _STATE_TYPES.get(state_name)
        if state_type is None:
            raise DomainInvariantViolation("Неизвестное состояние бронирования")

        booking._state = state_type()
        booking._approval_requested_at = _saved_optional_datetime(
            data.get("approval_requested_at")
        )
        booking._room_confirmed = bool(data.get("room_confirmed", False))
        booking._admin_order_confirmed = bool(
            data.get("admin_order_confirmed", False)
        )
        booking._checked_in_at = _saved_optional_datetime(data.get("checked_in_at"))
        booking._no_show_at = _saved_optional_datetime(data.get("no_show_at"))
        booking._rejection_reason = data.get("rejection_reason")

        # Проверяем, что восстановленное состояние не противоречиво
        if booking.state == "ready" and not booking._room_confirmed:
            raise DomainInvariantViolation(
                "Готовая бронь должна иметь подтверждение комнаты"
            )
        if (
            booking.state == "ready"
            and booking.requires_admin_order
            and not booking._admin_order_confirmed
        ):
            raise DomainInvariantViolation(
                "Для готовой брони должен быть подтвержден заказ администратора"
            )
        if (
            booking.state == "under_approval"
            and booking._approval_requested_at is None
        ):
            raise DomainInvariantViolation(
                "Для состояния under_approval требуется время запроса согласования"
            )
        if booking.state == "no_show" and booking._no_show_at is None:
            raise DomainInvariantViolation(
                "Для состояния no_show требуется время фиксации неявки"
            )

        return booking


# Порты репозиториев

class RoomRepository(Protocol):
    def get(self, room_id: RoomId) -> MeetingRoom: ...
    def save(self, room: MeetingRoom) -> None: ...


class BookingRepository(Protocol):
    def get(self, booking_id: BookingId) -> Booking: ...
    def add(self, booking: Booking) -> None: ...
    def save(self, booking: Booking) -> None: ...
    def list_by_room(self, room_id: RoomId) -> list[Booking]: ...
    def list_by_employee(self, employee_id: EmployeeId) -> list[Booking]: ...
    def list_all(self) -> list[Booking]: ...


# In-memory репозитории. 
# Данные храним как словари-снимки, чтобы выдача наружу всегда была новой копией, а не ссылкой на внутренний объект.

class InMemoryRoomRepository:
    def __init__(self) -> None:
        self._data: dict[int, dict] = {}

    def get(self, room_id: RoomId) -> MeetingRoom:
        if room_id.value not in self._data:
            raise EntityNotFound("Переговорная комната не найдена")
        # .copy() — чтобы фабрика не меняла словарь в репозитории
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
        # add именно для новых броней save для существующих
        # чтобы случайно не перезаписать чужую бронь с тем же id
        if booking.id.value in self._data:
            raise DomainInvariantViolation("ID бронирования уже используется")
        self._data[booking.id.value] = booking.snapshot()

    def save(self, booking: Booking) -> None:
        if booking.id.value not in self._data:
            raise EntityNotFound("Нельзя обновить несуществующее бронирование")
        self._data[booking.id.value] = booking.snapshot()

    def list_by_room(self, room_id: RoomId) -> list[Booking]:
        return [
            BookingFactory.restore(data.copy())
            for data in self._data.values()
            if data["room_id"] == room_id.value
        ]

    def list_by_employee(self, employee_id: EmployeeId) -> list[Booking]:
        return [
            BookingFactory.restore(data.copy())
            for data in self._data.values()
            if data["employee_id"] == employee_id.value
        ]

    def list_all(self) -> list[Booking]:
        return [BookingFactory.restore(data.copy()) for data in self._data.values()]