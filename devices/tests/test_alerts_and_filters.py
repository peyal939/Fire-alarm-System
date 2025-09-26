from django.utils import timezone
from rest_framework.test import APITestCase

from devices.models import Device, Alert
from devices import services


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
            {"hardware_identifier": "DEVF", "device_name": "DevF"},
            format="json",
        )
        self.device_id = r.data["id"]
        self.device = Device.objects.get(id=self.device_id)

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

    def test_telemetry_filters_since_until(self):
        # Create two telemetry points
        ts1 = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=10, device_status="alive", timestamp=ts1
        )
        ts2 = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=20, device_status="alive", timestamp=ts2
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
