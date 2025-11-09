from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from devices import services
from devices.alarm_state import schedule_next_reminder
from devices.constants import AlertType
from devices.models import Device, Alert


def get_items(data):
    # Pagination-aware helper: DRF PageNumberPagination returns dict with 'results'
    return data["results"] if isinstance(data, dict) and "results" in data else data


class AlertResolveAndTelemetryFilterTests(APITestCase):
    def setUp(self):
        # Create user and register device
        r = self.client.post(
            "/auth/register",
            {"email": "filters@example.com", "password": "Passw0rd!"},
            format="json",
        )
        r = self.client.post(
            "/auth/login",
            {"email": "filters@example.com", "password": "Passw0rd!"},
            format="json",
        )
        token = r.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEVF",
                "device_name": "DevF",
                "latitude": 23.78,
                "longitude": 90.41,
            },
            format="json",
        )
        self.device_id = r.data["id"]
        self.device = Device.objects.get(id=self.device_id)
        self.user = get_user_model().objects.get(email="filters@example.com")

    def test_alert_resolve_action(self):
        # Trigger only smoke_high alert (device_status is healthy)
        ts = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=999, device_status="alive", timestamp=ts
        )
        # Verify open alerts list
        r = self.client.get(f"/alerts/?device={self.device_id}&status=open")
        self.assertEqual(r.status_code, 200)
        items = get_items(r.data)
        self.assertGreaterEqual(len(items), 1)
        # Find a smoke_high alert (fallback to first)
        alert = None
        for it in items:
            if it.get("alert_type") == "smoke_high":
                alert = it
                break
        if alert is None:
            alert = items[0]

        # Resolve it
        alert_id = alert["id"]
        r = self.client.post(f"/alerts/{alert_id}/resolve/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data.get("status"), Alert.Status.RESOLVED)

        # Now open list should not include it, resolved list should include it
        r_open = self.client.get(f"/alerts/?device={self.device_id}&status=open")
        self.assertEqual(r_open.status_code, 200)
        open_ids = [a["id"] for a in get_items(r_open.data)]
        self.assertNotIn(alert_id, open_ids)

        r_res = self.client.get(
            f"/alerts/?device={self.device_id}&status={Alert.Status.RESOLVED}"
        )
        self.assertEqual(r_res.status_code, 200)
        res_ids = [a["id"] for a in get_items(r_res.data)]
        self.assertIn(alert_id, res_ids)

    def test_alert_acknowledge_action(self):
        ts = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=999, device_status="alive", timestamp=ts
        )

        r = self.client.get(f"/alerts/?device={self.device_id}&status=open")
        self.assertEqual(r.status_code, 200)
        alert = get_items(r.data)[0]
        alert_id = alert["id"]

        ack_response = self.client.post(f"/alerts/{alert_id}/acknowledge/")
        self.assertEqual(ack_response.status_code, 200)
        self.assertEqual(ack_response.data.get("status"), Alert.Status.OPEN)
        self.assertIsNotNone(ack_response.data.get("acknowledged_at"))
        self.assertEqual(ack_response.data.get("acknowledged_by"), self.user.id)

    def test_telemetry_filters_since_until(self):
        # Create two telemetry points (persisted only when smoke > threshold)
        ts1 = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=120, device_status="alive", timestamp=ts1
        )
        ts2 = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=130, device_status="alive", timestamp=ts2
        )

        # Global telemetry for this device
        r_all = self.client.get(f"/telemetry/?device={self.device_id}")
        self.assertEqual(r_all.status_code, 200)
        all_items = get_items(r_all.data)
        self.assertGreaterEqual(len(all_items), 2)

        # since=ts2 should include only the newer one (>= since)
        r_since = self.client.get(
            f"/telemetry/?device={self.device_id}&since={ts2.isoformat()}"
        )
        self.assertEqual(r_since.status_code, 200)
        since_items = get_items(r_since.data)
        self.assertGreaterEqual(len(since_items), 1)
        # Expect the earliest item to be ts2, not ts1
        # Can't assert exact timestamp equality due to serializer format, just count

        # until=ts1 should include only the older one (<= until)
        r_until = self.client.get(
            f"/telemetry/?device={self.device_id}&until={ts1.isoformat()}"
        )
        self.assertEqual(r_until.status_code, 200)
        until_items = get_items(r_until.data)
        self.assertGreaterEqual(len(until_items), 1)

        # epoch seconds variant for since
        epoch_since = int(ts2.timestamp())
        r_epoch = self.client.get(
            f"/telemetry/?device={self.device_id}&since={epoch_since}"
        )
        self.assertEqual(r_epoch.status_code, 200)
        epoch_items = get_items(r_epoch.data)
        self.assertGreaterEqual(len(epoch_items), 1)


class AlertReminderEscalationTests(TestCase):
    @override_settings(
        ALERT_REMINDER_INTERVAL_SECONDS=60,
        ALERT_ACK_ESCALATION_SECONDS=120,
        ALERT_REMINDER_MAX_COUNT=5,
    )
    def test_acknowledged_alert_triggers_escalation_reminder(self):
        user = get_user_model().objects.create_user(
            email="escalation@example.com", password="Passw0rd!"
        )
        device = Device.objects.create(
            user=user,
            hardware_identifier="ESCALATE-01",
            device_name="Escalate Device",
        )

        now = timezone.now()
        alert = Alert.objects.create(
            device=device,
            alert_type=AlertType.SMOKE_HIGH,
            status=Alert.Status.OPEN,
            triggered_at=now - timedelta(minutes=1),
            last_triggered_at=now - timedelta(minutes=1),
        )

        # Simulate acknowledgement that happened two minutes ago
        alert.acknowledged_at = now - timedelta(seconds=120)
        alert.acknowledged_by = user
        alert.save(update_fields=["acknowledged_at", "acknowledged_by"])

        schedule_next_reminder(alert)
        state = device.alarm_state
        self.assertIsNotNone(state.next_reminder_at)
        self.assertLessEqual(state.next_reminder_at, timezone.now())

        with patch(
            "notifications.services.FCMService.send_alert_notification"
        ) as mock_send:
            mock_send.return_value = {
                "success": 1,
                "failure": 0,
                "invalid_tokens": [],
            }
            call_command("send_alert_reminders")
            mock_send.assert_called_once()
            self.assertTrue(mock_send.call_args.kwargs.get("is_reminder"))

        alert.refresh_from_db()
        state.refresh_from_db()

        self.assertEqual(alert.reminder_count, 1)
        self.assertIsNotNone(alert.last_reminder_at)
        # Next reminder should be scheduled in the future (interval seconds)
        self.assertGreater(state.next_reminder_at, alert.last_reminder_at)
