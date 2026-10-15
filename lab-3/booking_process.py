
from __future__ import annotations

from datetime import datetime, timedelta

from meeting_room_ddd import (
    AdminOrderRequested,
    ApprovalRequested,
    Booking,
    BookingAvailabilityService,
    BookingId,
    BookingPeriod,
    BookingRepository,
    Clock,
    DomainInvariantViolation,
    EmployeeId,
    GatewayUnresolved,
    MeetingRoom,
    ParticipantCount,
    RoomId,
    RoomRepository,
)

class BookingProcess:
    def __init__(
        self,
        rooms: RoomRepository,
        bookings: BookingRepository,
        clock: Clock | None = None,
    ) -> None:
        # Репозитории и часы приходят снаружи сервис
        self._rooms = rooms
        self._bookings = bookings
        self._clock: Clock = clock or _SystemClock()
        # Буфер событий, которые агрегат накопил во время сценария
        self._published_events: list[object] = []

    # Работа с буфером событий 

    @property
    def published_events(self) -> tuple[object, ...]:
        return tuple(self._published_events)

    def pull_events(self) -> list[object]:
        events = self._published_events.copy()
        self._published_events.clear()
        return events

    def _save(self, booking: Booking) -> None:
        # Сохраняем бронь и сразу берём её события в свой буфер
        # Так адаптер может потом прочитать их одним вызовом pull_events()
        self._bookings.save(booking)
        for event in booking.pull_events():
            self._published_events.append(event)

    # Создание заявки

    def create_booking_request(
        self,
        booking_id: BookingId,
        room_id: RoomId,
        employee_id: EmployeeId,
        period: BookingPeriod,
        participants: ParticipantCount,
        *,
        needs_equipment: bool = False,
        needs_catering: bool = False,
    ) -> Booking:
        # Комната должна существовать если нет репозиторий отправит EntityNotFound
        self._rooms.get(room_id)
        booking = Booking(
            booking_id,
            room_id,
            employee_id,
            period,
            participants,
            needs_equipment=needs_equipment,
            needs_catering=needs_catering,
        )
        self._bookings.add(booking)
        return booking

    # Предикаты шлюзов BPMN каждый шлюз именованная функция чтобы на схеме и в коде было одно и то же название.

    def is_large_room(self, room: MeetingRoom) -> bool:
        return room.capacity.value > 10

    def has_large_room_restriction(
        self, employee_id: EmployeeId, now: datetime
    ) -> bool:
        if not isinstance(now, datetime):
            raise DomainInvariantViolation("Текущее время должно быть datetime")
        # Считаем неявки сотрудника за текущий месяц. Если их >= 3 крупные комнаты для него закрыты до конца месяца
        month_no_shows = 0
        for booking in self._bookings.list_by_employee(employee_id):
            if (
                booking.state == "no_show"
                and booking.no_show_at is not None
                and booking.no_show_at.year == now.year
                and booking.no_show_at.month == now.month
            ):
                month_no_shows += 1
        return month_no_shows >= 3

    def can_book_large_room(
        self, booking: Booking, room: MeetingRoom, now: datetime
    ) -> bool:
        if not self.is_large_room(room):
            return True
        return not self.has_large_room_restriction(booking.employee_id, now)

    def is_within_office_hours(
        self, booking: Booking, room: MeetingRoom
    ) -> bool:
        # Делегируем проверку агрегату комнаты там инвариант
        return room.is_within_office_hours(booking.period)

    def has_enough_capacity(
        self, booking: Booking, room: MeetingRoom
    ) -> bool:
        return room.has_enough_capacity(booking.participants)

    def is_room_available(self, booking: Booking) -> bool:
        existing = self._bookings.list_by_room(booking.room_id)
        return BookingAvailabilityService.is_available(booking, existing)

    def requires_approval(
        self, booking: Booking, room: MeetingRoom
    ) -> bool:
        # Согласование нужно для крупной комнаты или встречи длиннее 4 часов
        longer_than_four_hours = booking.period.duration > timedelta(hours=4)
        return room.capacity.value > 10 or longer_than_four_hours

    def needs_admin_order(self, booking: Booking) -> bool:
        return booking.requires_admin_order

    def has_three_no_shows(
        self, employee_id: EmployeeId, now: datetime
    ) -> bool:
        return self.has_large_room_restriction(employee_id, now)

    # Отдельные задачи проверки

    def check_large_room_permission(
        self, booking_id: BookingId, now: datetime
    ) -> bool:
        booking = self._bookings.get(booking_id)
        room = self._rooms.get(booking.room_id)
        return self.can_book_large_room(booking, room, now)

    def check_office_hours(self, booking_id: BookingId) -> bool:
        booking = self._bookings.get(booking_id)
        room = self._rooms.get(booking.room_id)
        return self.is_within_office_hours(booking, room)

    def check_capacity(self, booking_id: BookingId) -> bool:
        booking = self._bookings.get(booking_id)
        room = self._rooms.get(booking.room_id)
        return self.has_enough_capacity(booking, room)

    def check_room_availability(self, booking_id: BookingId) -> bool:
        booking = self._bookings.get(booking_id)
        return self.is_room_available(booking)

    # Маршрутизация начальных шлюзов. 

    def process_initial_checks(
        self, booking_id: BookingId, now: datetime
    ) -> Booking:
        booking = self._bookings.get(booking_id)
        room = self._rooms.get(booking.room_id)

        # 1 Может ли сотрудник вообще бронировать крупную комнату
        if not self.can_book_large_room(booking, room, now):
            booking.reject("Действует ограничение на бронирование крупной комнаты")
            self._save(booking)
            return booking

        # 2 Попадает ли интервал в рабочие часы офиса
        if not self.is_within_office_hours(booking, room):
            booking.reject("Бронирование находится вне рабочих часов")
            self._save(booking)
            return booking

        # 3 Хватает ли мест в комнате
        if not self.has_enough_capacity(booking, room):
            booking.reject("Количество участников превышает вместимость комнаты")
            self._save(booking)
            return booking

        # 4 Не занята ли комната на это время другой бронью
        if not self.is_room_available(booking):
            booking.reject("Комната занята на выбранное время")
            self._save(booking)
            return booking

        # 5 Нужно ли согласование руководителя
        if self.requires_approval(booking, room):
            booking.request_approval(now)
        else:
            booking.skip_approval()

        self._save(booking)
        return booking

    # Согласование

    def send_approval_request(
        self, booking_id: BookingId, now: datetime
    ) -> ApprovalRequested:
        booking = self._bookings.get(booking_id)
        booking.request_approval(now)
        self._save(booking)
        # Последнее событие в буфере ApprovalRequested
        return self._published_events[-1] 

    def approve_by_manager(self, booking_id: BookingId) -> Booking:
        booking = self._bookings.get(booking_id)
        booking.approve()
        self._save(booking)
        return booking

    def reject_by_manager(self, booking_id: BookingId) -> Booking:
        booking = self._bookings.get(booking_id)
        booking.reject_by_manager()
        self._save(booking)
        return booking

    def on_approval_timeout(
        self, booking_id: BookingId, now: datetime
    ) -> Booking:
        # Метод под событие таймера вызывается, когда 24 часа истекли
        booking = self._bookings.get(booking_id)
        booking.on_approval_timeout(now)
        self._save(booking)
        return booking

    # Параллельные ветви подготовки 

    def confirm_room(self, booking_id: BookingId) -> Booking:
        booking = self._bookings.get(booking_id)
        booking.confirm_room()
        self._save(booking)
        return booking

    def send_admin_request(self, booking_id: BookingId) -> AdminOrderRequested:
        booking = self._bookings.get(booking_id)
        # Если заказ администратору не нужен это ошибка шлюза
        if not self.needs_admin_order(booking):
            raise GatewayUnresolved(
                "Ветка администратора не применяется: оборудование и кейтеринг не требуются"
            )
        event = booking.note_admin_request()
        self._save(booking)
        return event

    def confirm_admin_order(self, booking_id: BookingId) -> Booking:
        booking = self._bookings.get(booking_id)
        booking.confirm_admin_order()
        self._save(booking)
        return booking

    # Отмена, начало встречи, отметка

    def cancel_booking(self, booking_id: BookingId, now: datetime) -> Booking:
        booking = self._bookings.get(booking_id)
        booking.cancel(now)
        self._save(booking)
        return booking

    def on_meeting_start(
        self, booking_id: BookingId, now: datetime
    ) -> Booking:
        # Метод под промежуточное событие таймера наступило время встречи
        booking = self._bookings.get(booking_id)
        booking.on_meeting_start(now)
        self._save(booking)
        return booking

    def check_in(self, booking_id: BookingId, now: datetime) -> Booking:
        booking = self._bookings.get(booking_id)
        booking.check_in(now)
        self._save(booking)
        return booking

    def on_check_in_timeout(
        self, booking_id: BookingId, now: datetime
    ) -> Booking:
        # Метод под граничный таймер 15 минут на отметку истекли
        booking = self._bookings.get(booking_id)
        booking.on_check_in_timeout(now)
        self._save(booking)
        return booking

    # Вспомогательные методы под задачи BPMN

    def release_room(self, booking_id: BookingId) -> Booking:
        # просто проверяем, что бронь действительно не блокирует слот иначе это ошибка вызова
        booking = self._bookings.get(booking_id)
        if booking.blocks_room:
            raise DomainInvariantViolation(
                "Комнату нельзя освободить, пока бронирование активно"
            )
        return booking

    def record_no_show(self, booking_id: BookingId) -> datetime:
        # Зафиксировать неявку возвращает время неявки 
        booking = self._bookings.get(booking_id)
        if booking.state != "no_show" or booking.no_show_at is None:
            raise DomainInvariantViolation("Неявка ещё не зафиксирована")
        return booking.no_show_at


ProcessDecisionError = GatewayUnresolved