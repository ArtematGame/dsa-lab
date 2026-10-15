from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import datetime, time, timedelta
from typing import Any

from flask import Flask, jsonify, request

from adapters import ClockMovedBack, SystemClock
from booking_process import BookingProcess
from meeting_room_ddd import (
    Booking,
    BookingId,
    BookingPeriod,
    Capacity,
    DomainInvariantViolation,
    EmployeeId,
    EntityNotFound,
    GatewayUnresolved,
    InMemoryBookingRepository,
    InMemoryRoomRepository,
    InvalidValueObject,
    MeetingRoom,
    OfficeHours,
    ParticipantCount,
    RoomId,
    TransitionNotAllowed,
)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))

app = Flask(__name__)

# Создаются один раз при запуске приложения
clock = SystemClock()
clock.move_to(datetime(2026, 10, 19, 9, 0))
rooms_repo = InMemoryRoomRepository()
bookings_repo = InMemoryBookingRepository()
process = BookingProcess(rooms_repo, bookings_repo, clock)

# Предзаполненные переговорные комнаты
rooms_repo.save(
    MeetingRoom(
        RoomId(1),
        "Малая переговорная",
        Capacity(8),
        OfficeHours(time(9, 0), time(18, 0)),
    )
)
rooms_repo.save(
    MeetingRoom(
        RoomId(2),
        "Большая переговорная",
        Capacity(20),
        OfficeHours(time(9, 0), time(18, 0)),
    )
)

# История доменных событий по каждому бронированию
event_history: dict[int, list[dict[str, Any]]] = {}


def _serialize_event(ev: object) -> dict[str, Any]:
    raw = asdict(ev) 
    out: dict[str, Any] = {"event": type(ev).__name__}
    for k, v in raw.items():
        if hasattr(v, "value"):
            out[k] = v.value
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _flush_events() -> None:
    for ev in process.pull_events():
        bid = getattr(ev, "booking_id", None)
        key = bid.value if hasattr(bid, "value") else 0
        event_history.setdefault(key, []).append(_serialize_event(ev))


def _booking_response(booking: Booking) -> dict[str, Any]:
    _flush_events()
    snap = booking.snapshot()
    snap["allowed_events"] = booking.allowed_events()
    snap["events"] = event_history.get(booking.id.value, [])
    return snap


def _parse_iso_dt(raw: Any, field: str) -> datetime:
    if not isinstance(raw, str):
        raise InvalidValueObject(f"Поле '{field}' должно быть строкой ISO 8601")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidValueObject(f"Некорректный формат даты в '{field}'") from exc


# Общий обработчик исключений
@app.errorhandler(TransitionNotAllowed)
def handle_transition_not_allowed(exc: TransitionNotAllowed):
    return jsonify({"error": "TRANSITION_NOT_ALLOWED", "message": str(exc)}), 409


@app.errorhandler(InvalidValueObject)
def handle_invalid_vo(exc: InvalidValueObject):
    return jsonify({"error": "INVALID_VALUE_OBJECT", "message": str(exc)}), 422


@app.errorhandler(DomainInvariantViolation)
def handle_invariant(exc: DomainInvariantViolation):
    return jsonify({"error": "INVARIANT_VIOLATION", "message": str(exc)}), 422


@app.errorhandler(ClockMovedBack)
def handle_clock_back(exc: ClockMovedBack):
    return jsonify({"error": "CLOCK_MOVED_BACK", "message": str(exc)}), 422


@app.errorhandler(EntityNotFound)
def handle_not_found(exc: EntityNotFound):
    return jsonify({"error": "ENTITY_NOT_FOUND", "message": str(exc)}), 404


@app.errorhandler(GatewayUnresolved)
def handle_gateway(exc: GatewayUnresolved):
    return jsonify({"error": "GATEWAY_UNRESOLVED", "message": str(exc)}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok", "now": clock.now().isoformat()}), 200


@app.post("/rooms")
def create_room():
    data = request.get_json(silent=True) or {}
    room = MeetingRoom(
        RoomId(data.get("room_id")),
        data.get("name", ""),
        Capacity(data.get("capacity")),
        OfficeHours(
            time.fromisoformat(str(data.get("office_start", ""))),
            time.fromisoformat(str(data.get("office_end", ""))),
        ),
    )
    rooms_repo.save(room)
    return jsonify(room.snapshot()), 201


@app.get("/bookings/<int:booking_id>")
def get_booking(booking_id: int):
    booking = bookings_repo.get(BookingId(booking_id))
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings")
def create_booking():
    data = request.get_json(silent=True) or {}
    start = _parse_iso_dt(data.get("start"), "start")
    end = _parse_iso_dt(data.get("end"), "end")
    booking = process.create_booking_request(
        BookingId(data.get("booking_id")),
        RoomId(data.get("room_id")),
        EmployeeId(data.get("employee_id")),
        BookingPeriod(start, end),
        ParticipantCount(data.get("participants")),
        needs_equipment=data.get("needs_equipment", False),
        needs_catering=data.get("needs_catering", False),
    )
    event_history.setdefault(booking.id.value, [])
    return jsonify(_booking_response(booking)), 201


@app.post("/bookings/<int:booking_id>/initial-checks")
def initial_checks(booking_id: int):
    booking = process.process_initial_checks(BookingId(booking_id), clock.now())
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/request-approval")
def request_approval(booking_id: int):
    bid = BookingId(booking_id)
    process.send_approval_request(bid, clock.now())
    return jsonify(_booking_response(bookings_repo.get(bid))), 200


@app.post("/bookings/<int:booking_id>/approve")
def approve(booking_id: int):
    booking = process.approve_by_manager(BookingId(booking_id))
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/reject-by-manager")
def reject_by_manager(booking_id: int):
    booking = process.reject_by_manager(BookingId(booking_id))
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/confirm-room")
def confirm_room(booking_id: int):
    booking = process.confirm_room(BookingId(booking_id))
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/send-admin-request")
def send_admin_request(booking_id: int):
    bid = BookingId(booking_id)
    process.send_admin_request(bid)
    return jsonify(_booking_response(bookings_repo.get(bid))), 200


@app.post("/bookings/<int:booking_id>/confirm-admin-order")
def confirm_admin_order(booking_id: int):
    booking = process.confirm_admin_order(BookingId(booking_id))
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/cancel")
def cancel(booking_id: int):
    booking = process.cancel_booking(BookingId(booking_id), clock.now())
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/start-meeting")
def start_meeting(booking_id: int):
    booking = process.on_meeting_start(BookingId(booking_id), clock.now())
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/check-in")
def check_in(booking_id: int):
    booking = process.check_in(BookingId(booking_id), clock.now())
    return jsonify(_booking_response(booking)), 200


@app.post("/bookings/<int:booking_id>/release-room")
def release_room(booking_id: int):
    booking = process.release_room(BookingId(booking_id))
    return jsonify(_booking_response(booking)), 200


@app.post("/internal/tick")
def internal_tick():
    data = request.get_json(silent=True) or {}
    if "now" in data and data["now"] is not None:
        target = _parse_iso_dt(data["now"], "now")
        clock.move_to(target)
    now = clock.now()
    triggered: list[dict[str, Any]] = []

    for b in bookings_repo.list_all():
        allowed = b.allowed_events()
        snap = b.snapshot()
        if "on_approval_timeout" in allowed and snap["approval_requested_at"]:
            req_at = datetime.fromisoformat(snap["approval_requested_at"])
            if now >= req_at + timedelta(hours=24):
                process.on_approval_timeout(b.id, now)
                triggered.append({"booking_id": b.id.value, "event": "on_approval_timeout"})
                continue

        if "on_meeting_start" in allowed and now >= b.period.start:
            process.on_meeting_start(b.id, now)
            triggered.append({"booking_id": b.id.value, "event": "on_meeting_start"})
            b = bookings_repo.get(b.id)
            allowed = b.allowed_events()

        if "on_check_in_timeout" in allowed and now >= b.period.start + timedelta(minutes=15):
            process.on_check_in_timeout(b.id, now)
            triggered.append({"booking_id": b.id.value, "event": "on_check_in_timeout"})

    _flush_events()
    return jsonify({"now": now.isoformat(), "triggered": triggered}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
