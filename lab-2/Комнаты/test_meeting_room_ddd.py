import unittest
from datetime import datetime, time

# импорт классов из основного файла
from meeting_room_ddd import (
    BookingFactory,
    BookingId,
    BookingPeriod,
    BookingService,
    Capacity,
    DomainInvariantViolation,
    EmployeeId,
    InMemoryBookingRepository,
    InMemoryRoomRepository,
    InvalidValueObject,
    MeetingRoom,
    MeetingRoomFactory,
    OfficeHours,
    ParticipantCount,
    RoomId,
)


class MeetingRoomDDDTests(unittest.TestCase):

    def setUp(self):
        # создаем пустые хранилища комнат и бронирований
        self.rooms = InMemoryRoomRepository()
        self.bookings = InMemoryBookingRepository()

        # создаем сервис бронирования
        self.service = BookingService(self.rooms, self.bookings)

        # добавляем комнату на 10 человек которая работает с 9:00 до 18:00
        self.rooms.save(
            MeetingRoom(
                RoomId(1),
                "Переговорная 1",
                Capacity(10),
                OfficeHours(time(9, 0), time(18, 0)),
            )
        )

        # интервал с 10:00 до 11:00
        self.period = BookingPeriod(
            datetime(2026, 9, 30, 10, 0),
            datetime(2026, 9, 30, 11, 0),
        )

    def create(self, booking_id=1, room_id=1, employee_id=1, period=None, participants=5):
        # вспомогательный метод чтобы не писать создание брони в каждом тесте
        return self.service.create_booking(
            BookingId(booking_id),
            RoomId(room_id),
            EmployeeId(employee_id),
            period or self.period,
            ParticipantCount(participants),
        )

    def test_create_booking(self):
        # проверяем обычное бронирование комнаты
        booking = self.create()

        # бронь должна создаться и иметь активный статус
        self.assertEqual("active", booking.status)

        # в хранилище должна появиться запись с ID 1
        self.assertIn(1, self.bookings._data)

    def test_too_many_participants(self):
        # комната рассчитана на 10 человек поэтому 11 человек разместить нельзя
        with self.assertRaises(DomainInvariantViolation):
            self.create(participants=11)

        # неправильная бронь не должна сохраниться
        self.assertNotIn(1, self.bookings._data)

    def test_before_office_hours(self):
        # проверяем что бронь нельзя начать раньше открытия офиса
        early_period = BookingPeriod(
            datetime(2026, 9, 30, 8, 30),
            datetime(2026, 9, 30, 10, 0),
        )

        with self.assertRaises(DomainInvariantViolation):
            self.create(period=early_period)

    def test_after_office_hours(self):
        # проверяем что бронь нельзя закончить после закрытия офиса
        late_period = BookingPeriod(
            datetime(2026, 9, 30, 17, 0),
            datetime(2026, 9, 30, 18, 30),
        )

        with self.assertRaises(DomainInvariantViolation):
            self.create(period=late_period)

    def test_invalid_period(self):
        # окончание бронирования не может быть раньше начала
        with self.assertRaises(InvalidValueObject):
            BookingPeriod(
                datetime(2026, 9, 30, 12, 0),
                datetime(2026, 9, 30, 11, 0),
            )

    def test_prevents_overlap(self):
        # создаем первую бронь с 10 до 11
        self.create()

        # вторая бронь с 10:30 до 11:30 пересекается с первой
        second_period = BookingPeriod(
            datetime(2026, 9, 30, 10, 30),
            datetime(2026, 9, 30, 11, 30),
        )

        with self.assertRaises(DomainInvariantViolation):
            self.create(booking_id=2, employee_id=2, period=second_period)

        # вторая бронь не должна сохраниться
        self.assertNotIn(2, self.bookings._data)

    def test_booking_after_previous_is_allowed(self):
        # первая бронь заканчивается в 11:00
        self.create()

        # вторая начинается ровно в 11:00 поэтому пересечения нет
        second_period = BookingPeriod(
            datetime(2026, 9, 30, 11, 0),
            datetime(2026, 9, 30, 12, 0),
        )

        booking = self.create(booking_id=2, employee_id=2, period=second_period)
        self.assertEqual(BookingId(2), booking.id)

    def test_same_time_different_room_is_allowed(self):
        # добавляем вторую комнату
        self.rooms.save(
            MeetingRoom(
                RoomId(2),
                "Переговорная 2",
                Capacity(8),
                OfficeHours(time(9, 0), time(18, 0)),
            )
        )

        # бронируем первую комнату
        self.create()

        # вторую комнату можно забронировать на то же самое время
        booking = self.create(booking_id=2, room_id=2, employee_id=2)
        self.assertEqual(RoomId(2), booking.room_id)

    def test_duplicate_booking_id(self):
        # создаем первую бронь с ID 1
        self.create()

        # добавляем вторую комнату чтобы не было пересечения по комнате
        self.rooms.save(
            MeetingRoom(
                RoomId(2),
                "Переговорная 2",
                Capacity(8),
                OfficeHours(time(9, 0), time(18, 0)),
            )
        )

        # одинаковый ID бронирования использовать нельзя
        with self.assertRaises(DomainInvariantViolation):
            self.create(booking_id=1, room_id=2, employee_id=2)

    def test_invalid_values(self):
        # проверяем неправильные значения объектов-значений
        for construct in [
            lambda: RoomId(0),
            lambda: EmployeeId(-1),
            lambda: BookingId(True),
            lambda: Capacity(0),
            lambda: ParticipantCount(0),
        ]:
            with self.assertRaises(InvalidValueObject):
                construct()

    def test_room_factory_rejects_wrong_capacity(self):
        # получаем сохраненное состояние комнаты
        state = self.rooms.get(RoomId(1)).snapshot()

        # специально делаем вместимость неправильной
        state["capacity"] = -5

        # фабрика должна заново проверить данные и вызвать ошибку
        with self.assertRaises(InvalidValueObject):
            MeetingRoomFactory.restore(state)

    def test_booking_factory_rejects_wrong_status(self):
        # создаем обычную бронь
        self.create()

        # получаем сохраненное состояние
        state = self.bookings.get(BookingId(1)).snapshot()

        # специально подменяем статус
        state["status"] = "wrong"

        # фабрика должна заметить неправильное состояние
        with self.assertRaises(DomainInvariantViolation):
            BookingFactory.restore(state)


if __name__ == "__main__":
    # запускаем все тесты
    unittest.main()
