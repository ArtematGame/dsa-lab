# Тесты прикладного сервиса и доменной модели.
# Покрывают инварианты ЛР2 и переходы жизненного цикла из ЛР3.

import unittest
from datetime import datetime, time, timedelta

from adapters import SystemClock
from booking_process import BookingProcess, GatewayUnresolved
from meeting_room_ddd import (
    AdminOrderRequested,
    ApprovalRequested,
    BookingId,
    BookingPeriod,
    Capacity,
    DomainInvariantViolation,
    EmployeeId,
    InMemoryBookingRepository,
    InMemoryRoomRepository,
    MeetingRoom,
    OfficeHours,
    ParticipantCount,
    RoomId,
    RoomConfirmed,
    TransitionNotAllowed,
)


class BookingProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        # Свежие репозитории на каждый тест — чтобы тесты не влияли друг на друга.
        self.rooms = InMemoryRoomRepository()
        self.bookings = InMemoryBookingRepository()
        self.process = BookingProcess(self.rooms, self.bookings, SystemClock())

        # Две комнаты: маленькая (10 мест) и большая (20 мест).
        # Разница нужна, чтобы проверять правило «крупная комната — согласование».
        self.rooms.save(
            MeetingRoom(
                RoomId(1),
                "Переговорная 1",
                Capacity(10),
                OfficeHours(time(9, 0), time(18, 0)),
            )
        )
        self.rooms.save(
            MeetingRoom(
                RoomId(2),
                "Большая переговорная",
                Capacity(20),
                OfficeHours(time(9, 0), time(18, 0)),
            )
        )

        # Общий стартовый момент для большинства тестов.
        self.start = datetime(2026, 10, 20, 10, 0)
        self.period = BookingPeriod(self.start, self.start + timedelta(hours=2))

    # Удобный хелпер, чтобы не писать по 10 строк в каждом тесте.
    def create(
        self,
        booking_id=1,
        room_id=1,
        employee_id=1,
        period=None,
        participants=5,
        equipment=False,
        catering=False,
    ):
        return self.process.create_booking_request(
            BookingId(booking_id),
            RoomId(room_id),
            EmployeeId(employee_id),
            period or self.period,
            ParticipantCount(participants),
            needs_equipment=equipment,
            needs_catering=catering,
        )

    # Хелпер: провести заявку до состояния ready без согласования.
    def prepare_without_approval(self, booking_id=1):
        self.process.process_initial_checks(
            BookingId(booking_id), datetime(2026, 10, 19, 12, 0)
        )
        return self.process.confirm_room(BookingId(booking_id))

    # --- Базовые проверки состояния ---

    def test_state_is_read_only(self):
        # Пытаемся присвоить state — должно упасть AttributeError,
        # потому что сеттера у свойства нет.
        booking = self.create()
        with self.assertRaises(AttributeError):
            booking.state = "ready"  # type: ignore[misc]

    def test_invalid_transition_raises_transition_not_allowed(self):
        # В submitted нельзя check_in — ждём TransitionNotAllowed
        # с понятным сообщением.
        booking = self.create()
        with self.assertRaises(TransitionNotAllowed) as ctx:
            booking.check_in(self.start)
        self.assertIn("submitted", str(ctx.exception))
        self.assertIn("check_in", str(ctx.exception))

    # --- Инварианты ---

    def test_capacity_rule_rejects_request(self):
        # 11 человек в комнату на 10 — отказ.
        self.create(participants=11)
        booking = self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        self.assertEqual("rejected", booking.state)
        self.assertIn("вместимость", booking.rejection_reason)

    def test_office_hours_rule_rejects_request(self):
        # Бронь с 8:30 — вне рабочих часов (с 9:00).
        early = BookingPeriod(
            datetime(2026, 10, 20, 8, 30),
            datetime(2026, 10, 20, 10, 0),
        )
        self.create(period=early)
        booking = self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        self.assertEqual("rejected", booking.state)
        self.assertIn("рабочих часов", booking.rejection_reason)

    def test_overlap_rule_rejects_second_request(self):
        # Первая бронь занимает 10:00–12:00. Вторая — 10:30–11:30.
        # Должна быть отклонена как пересекающаяся.
        self.create(booking_id=1)
        self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        self.process.confirm_room(BookingId(1))

        overlap = BookingPeriod(
            datetime(2026, 10, 20, 10, 30),
            datetime(2026, 10, 20, 11, 30),
        )
        self.create(booking_id=2, employee_id=2, period=overlap)
        booking = self.process.process_initial_checks(
            BookingId(2), datetime(2026, 10, 19, 12, 5)
        )
        self.assertEqual("rejected", booking.state)
        self.assertIn("занята", booking.rejection_reason)

    # --- Согласование ---

    def test_large_room_requires_approval_and_publishes_message(self):
        # Крупная комната → состояние under_approval + событие ApprovalRequested.
        self.create(room_id=2, participants=8)
        booking = self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        self.assertEqual("under_approval", booking.state)
        events = self.process.pull_events()
        self.assertEqual(1, len(events))
        self.assertIsInstance(events[0], ApprovalRequested)

    def test_more_than_four_hours_requires_approval(self):
        # Даже маленькая комната, но встреча 5 часов → согласование.
        long_period = BookingPeriod(
            self.start,
            self.start + timedelta(hours=5),
        )
        self.create(period=long_period)
        booking = self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        self.assertEqual("under_approval", booking.state)

    def test_approval_timeout_after_24_hours_rejects(self):
        # Согласование запросили в 10:00, ответа нет 24 часа → отказ.
        self.create(room_id=2)
        requested_at = datetime(2026, 10, 18, 10, 0)
        self.process.process_initial_checks(BookingId(1), requested_at)
        booking = self.process.on_approval_timeout(
            BookingId(1), requested_at + timedelta(hours=24)
        )
        self.assertEqual("rejected", booking.state)

    def test_approval_timeout_too_early_is_forbidden(self):
        # За 23 часа до дедлайна событие таймаута недопустимо.
        self.create(room_id=2)
        requested_at = datetime(2026, 10, 18, 10, 0)
        self.process.process_initial_checks(BookingId(1), requested_at)
        with self.assertRaises(DomainInvariantViolation):
            self.process.on_approval_timeout(
                BookingId(1), requested_at + timedelta(hours=23)
            )

    def test_manager_approval_moves_to_preparing(self):
        # Руководитель согласовал → preparing.
        self.create(room_id=2)
        self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        booking = self.process.approve_by_manager(BookingId(1))
        self.assertEqual("preparing", booking.state)

    # --- Параллельные ветви подготовки ---

    def test_without_admin_order_room_confirmation_makes_ready(self):
        # Если админ-заказ не нужен, достаточно подтвердить комнату → ready.
        self.create()
        booking = self.prepare_without_approval()
        self.assertEqual("ready", booking.state)
        self.assertTrue(booking.room_confirmed)

    def test_parallel_branch_stays_visible_until_both_done(self):
        # Нужны и комната, и админ-заказ. Пока одно не закрыто —
        # бронь остаётся в preparing. Это эмуляция параллельного шлюза.
        self.create(equipment=True)
        self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )

        event = self.process.send_admin_request(BookingId(1))
        self.assertIsInstance(event, AdminOrderRequested)

        # Подтвердили только комнату — всё ещё preparing.
        booking = self.process.confirm_room(BookingId(1))
        self.assertEqual("preparing", booking.state)
        self.assertTrue(booking.room_confirmed)
        self.assertFalse(booking.admin_order_confirmed)

        # Подтвердили заказ — теперь ready.
        booking = self.process.confirm_admin_order(BookingId(1))
        self.assertEqual("ready", booking.state)
        self.assertTrue(booking.admin_order_confirmed)

    def test_admin_branch_not_allowed_when_not_needed(self):
        # Если ни оборудование, ни кейтеринг не нужны — ветка администратора
        # не должна запускаться вообще. Это GatewayUnresolved.
        self.create()
        self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        with self.assertRaises(GatewayUnresolved):
            self.process.send_admin_request(BookingId(1))

    # --- Отмена, начало встречи, отметка ---

    def test_cancel_before_start(self):
        # За минуту до старта — можно отменить.
        self.create()
        self.prepare_without_approval()
        booking = self.process.cancel_booking(
            BookingId(1), self.start - timedelta(minutes=1)
        )
        self.assertEqual("cancelled", booking.state)

    def test_cancel_after_start_is_forbidden(self):
        # Ровно в момент старта — уже нельзя.
        self.create()
        self.prepare_without_approval()
        with self.assertRaises(DomainInvariantViolation):
            self.process.cancel_booking(BookingId(1), self.start)

    def test_check_in_within_15_minutes(self):
        # Отметка через 10 минут после начала — успеваем.
        self.create()
        self.prepare_without_approval()
        self.process.on_meeting_start(BookingId(1), self.start)
        booking = self.process.check_in(
            BookingId(1), self.start + timedelta(minutes=10)
        )
        self.assertEqual("held", booking.state)

    def test_no_show_after_15_minutes(self):
        # Через 15 минут никто не отметился — неявка.
        self.create()
        self.prepare_without_approval()
        self.process.on_meeting_start(BookingId(1), self.start)
        booking = self.process.on_check_in_timeout(
            BookingId(1), self.start + timedelta(minutes=15)
        )
        self.assertEqual("no_show", booking.state)
        self.assertIsNotNone(booking.no_show_at)

    # --- Правило трёх неявок ---

    def test_three_no_shows_block_large_room(self):
        # Три неявки за месяц → крупные комнаты сотруднику недоступны.
        employee = 7
        for i, day in enumerate((1, 2, 3), start=1):
            start = datetime(2026, 10, day, 10, 0)
            period = BookingPeriod(start, start + timedelta(hours=1))
            self.create(
                booking_id=i,
                room_id=1,
                employee_id=employee,
                period=period,
            )
            self.process.process_initial_checks(
                BookingId(i), start - timedelta(days=1)
            )
            self.process.confirm_room(BookingId(i))
            self.process.on_meeting_start(BookingId(i), start)
            self.process.on_check_in_timeout(
                BookingId(i), start + timedelta(minutes=15)
            )

        # Четвёртая заявка — уже в крупную комнату, должна быть отклонена.
        fourth_start = datetime(2026, 10, 25, 10, 0)
        self.create(
            booking_id=10,
            room_id=2,
            employee_id=employee,
            period=BookingPeriod(
                fourth_start, fourth_start + timedelta(hours=1)
            ),
        )
        booking = self.process.process_initial_checks(
            BookingId(10), datetime(2026, 10, 24, 12, 0)
        )
        self.assertEqual("rejected", booking.state)
        self.assertIn("ограничение", booking.rejection_reason)

    # --- Журнал событий ---

    def test_events_are_recorded_in_aggregate_journal(self):
        # Полный успешный путь без согласования и без админ-заказа:
        # submitted -> preparing -> ready.
        # Проверяем, что в журнале агрегата осели нужные доменные события.
        self.create()
        self.process.process_initial_checks(
            BookingId(1), datetime(2026, 10, 19, 12, 0)
        )
        # Забираем то, что накопилось после начальных проверок.
        # Тут будет событие отправки заявки руководителю либо пусто
        # (если согласование не требуется — skip_approval событий не пишет).
        initial_events = self.process.pull_events()
        self.assertEqual([], initial_events)

        # А теперь подтверждаем комнату — вот тут появляется RoomConfirmed.
        booking = self.process.confirm_room(BookingId(1))
        self.assertEqual("ready", booking.state)

        events = self.process.pull_events()
        self.assertTrue(
            any(isinstance(e, RoomConfirmed) for e in events),
            f"Ожидали RoomConfirmed в журнале, получили: {events}",
        )
        # На всякий случай проверим, что журнал агрегата пуст после выгрузки.
        self.assertEqual((), booking.events)


if __name__ == "__main__":
    unittest.main()