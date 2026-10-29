# -*- coding: utf-8 -*-
import json
import unittest

from app import app


class WebAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_full_section4_scenarios(self) -> None:
        # Health
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)

        # 1. Основной путь (P10 -> P12)
        r = self.client.post(
            "/bookings",
            json={
                "booking_id": 1,
                "room_id": 2,
                "employee_id": 101,
                "start": "2026-10-20T10:00:00",
                "end": "2026-10-20T12:00:00",
                "participants": 12,
                "needs_equipment": True,
                "needs_catering": False,
            },
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["state"], "submitted")

        r = self.client.post("/bookings/1/initial-checks")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"], "under_approval")

        r = self.client.post("/bookings/1/approve")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"], "preparing")

        r = self.client.post("/bookings/1/confirm-room")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"], "preparing")

        r = self.client.post("/bookings/1/send-admin-request")
        self.assertEqual(r.status_code, 200)

        r = self.client.post("/bookings/1/confirm-admin-order")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"], "ready")

        r = self.client.post("/internal/tick", json={"now": "2026-10-20T10:05:00"})
        self.assertEqual(r.status_code, 200)

        r = self.client.post("/bookings/1/check-in")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["state"], "held")

        # 2. Альтернативный путь 1 (таймер 24 часа -> rejected)
        self.client.post(
            "/bookings",
            json={
                "booking_id": 2,
                "room_id": 2,
                "employee_id": 102,
                "start": "2026-10-22T14:00:00",
                "end": "2026-10-22T16:00:00",
                "participants": 15,
            },
        )
        self.client.post("/bookings/2/initial-checks")
        self.client.post("/internal/tick", json={"now": "2026-10-21T11:00:00"})
        r = self.client.get("/bookings/2")
        self.assertEqual(r.get_json()["state"], "rejected")

        # 3. Альтернативный путь 2 (без согласования + отмена до начала -> cancelled)
        self.client.post(
            "/bookings",
            json={
                "booking_id": 3,
                "room_id": 1,
                "employee_id": 103,
                "start": "2026-10-22T10:00:00",
                "end": "2026-10-22T11:00:00",
                "participants": 5,
            },
        )
        self.client.post("/bookings/3/initial-checks")
        self.client.post("/bookings/3/confirm-room")
        r = self.client.post("/bookings/3/cancel")
        self.assertEqual(r.get_json()["state"], "cancelled")

        # 4. Три недопустимых события (409 Conflict)
        self.client.post(
            "/bookings",
            json={
                "booking_id": 4,
                "room_id": 2,
                "employee_id": 104,
                "start": "2026-10-23T10:00:00",
                "end": "2026-10-23T12:00:00",
                "participants": 14,
            },
        )
        r1 = self.client.post("/bookings/4/check-in")
        self.assertEqual(r1.status_code, 409)
        self.assertEqual(self.client.get("/bookings/4").get_json()["state"], "submitted")

        self.client.post("/bookings/4/initial-checks")
        r2 = self.client.post("/bookings/4/confirm-room")
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(self.client.get("/bookings/4").get_json()["state"], "under_approval")

        r3 = self.client.post("/bookings/3/approve")
        self.assertEqual(r3.status_code, 409)
        self.assertEqual(self.client.get("/bookings/3").get_json()["state"], "cancelled")

        # 5. Коды 422 и 404
        r422 = self.client.post(
            "/bookings",
            json={
                "booking_id": 5,
                "room_id": 1,
                "employee_id": 105,
                "start": "2026-10-23T10:00:00",
                "end": "2026-10-23T11:00:00",
                "participants": -3,
            },
        )
        self.assertEqual(r422.status_code, 422)

        r_clock = self.client.post("/internal/tick", json={"now": "2026-10-19T08:00:00"})
        self.assertEqual(r_clock.status_code, 422)

        r404 = self.client.get("/bookings/999")
        self.assertEqual(r404.status_code, 404)


if __name__ == "__main__":
    unittest.main()
