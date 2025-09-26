from django.utils import timezone
from rest_framework.test import APITestCase

from devices.models import Device, Alert
from devices import services


class IngestionAndAlertsTests(APITestCase):
    def setUp(self):
        r = self.client.post(
            "/auth/register",
            {"email": "c@example.com", "password": "Passw0rd!"},
            format="json",
        )
        r = self.client.post(
            "/auth/login",
            {"email": "c@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.token = r.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEVY",
                "device_name": "DevY",
                "latitude": 23.78,
                "longitude": 90.41,
            },
            format="json",
        )
        self.device_id = r.data["id"]
        self.device = Device.objects.get(id=self.device_id)

    def test_ingest_creates_alerts_and_resolves(self):
        ts1 = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=999, device_status="alert", timestamp=ts1
        )
        self.assertEqual(
            Alert.objects.filter(device=self.device, status=Alert.Status.OPEN).count(),
            2,
        )
        ts2 = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=0, device_status="alive", timestamp=ts2
        )
        self.assertEqual(
            Alert.objects.filter(device=self.device, status=Alert.Status.OPEN).count(),
            0,
        )

    def test_unknown_device_ignored(self):
        ts = timezone.now()
        ok = services.ingest_by_hardware_identifier(
            "UNKNOWN", smoke_level=10, device_status="alive", timestamp=ts
        )
        self.assertFalse(ok)
