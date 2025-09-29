from django.utils import timezone
from rest_framework.test import APITestCase

from devices.models import Device, Telemetry
from realtime.mqtt import process_payload


class MQTTIngestionTests(APITestCase):
    def setUp(self):
        # Register a user and login
        self.client.post(
            "/auth/register",
            {"email": "mqtt@example.com", "password": "Passw0rd!"},
            format="json",
        )
        r = self.client.post(
            "/auth/login",
            {"email": "mqtt@example.com", "password": "Passw0rd!"},
            format="json",
        )
        token = r.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Register a master and two slaves (one valid under master, one separate master)
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "MASTER-ING",
                "device_name": "Master ING",
                "latitude": 23.7,
                "longitude": 90.4,
            },
            format="json",
        )
        self.master = Device.objects.get(id=r.data["id"])

        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "SLAVE-OK",
                "device_name": "Slave OK",
                "latitude": 23.71,
                "longitude": 90.41,
                "device_role": Device.DeviceRole.SLAVE,
                "master_id": self.master.id,
            },
            format="json",
        )
        self.slave_ok = Device.objects.get(id=r.data["id"])

        # Another master and a slave attached to it (to test mismatched master enforcement)
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "MASTER-2",
                "device_name": "Master Two",
                "latitude": 23.72,
                "longitude": 90.42,
            },
            format="json",
        )
        self.master2 = Device.objects.get(id=r.data["id"])

        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "SLAVE-WRONG",
                "device_name": "Slave Wrong",
                "latitude": 23.73,
                "longitude": 90.43,
                "device_role": Device.DeviceRole.SLAVE,
                "master_id": self.master2.id,
            },
            format="json",
        )
        self.slave_wrong = Device.objects.get(id=r.data["id"])

    def test_composite_master_and_slaves_ingestion(self):
        ts = int(timezone.now().timestamp())
        payload = {
            "masterID": "MASTER-ING",
            "timestamp": ts,
            "status": "alive",
            "smoke": 10,
            "slaves": [
                {
                    "deviceID": "SLAVE-OK",
                    "timestamp": ts,
                    "status": "alive",
                    "smoke": 120,
                },
                {
                    "deviceID": "SLAVE-WRONG",
                    "timestamp": ts,
                    "status": "alive",
                    "smoke": 130,
                },
                {
                    "deviceID": "UNKNOWN-SLAVE",
                    "timestamp": ts,
                    "status": "alive",
                    "smoke": 140,
                },
            ],
        }

        # Ingest
        process_payload(payload)

        # Master gets updated last_seen and status regardless of smoke persistence rules
        self.master.refresh_from_db()
        self.assertEqual(self.master.status, "alive")
        self.assertIsNotNone(self.master.last_seen)

        # Slave-OK should have telemetry persisted (smoke>threshold)
        self.assertTrue(
            Telemetry.objects.filter(
                device=self.slave_ok, smoke_level__gte=120
            ).exists()
        )

        # Slave-WRONG is registered to another master; should be ignored (no telemetry persisted)
        self.assertFalse(
            Telemetry.objects.filter(
                device=self.slave_wrong, smoke_level__gte=130
            ).exists()
        )

        # Unknown slave ignored
        self.assertFalse(
            Telemetry.objects.filter(
                device__hardware_identifier="UNKNOWN-SLAVE"
            ).exists()
        )

    def test_composite_accepts_masterDeviceID_alias(self):
        ts = int(timezone.now().timestamp())
        payload = {
            "masterDeviceID": "MASTER-ING",
            "timestamp": ts,
            "status": "alive",
            "smoke": 7,
            "slaves": [
                {
                    "deviceID": "SLAVE-OK",
                    "timestamp": ts,
                    "status": "alive",
                    "smoke": 160,
                }
            ],
        }
        process_payload(payload)
        # Should ingest for the known slave
        self.assertTrue(
            Telemetry.objects.filter(
                device=self.slave_ok, smoke_level__gte=160
            ).exists()
        )

    def test_unknown_master_ignored(self):
        ts = int(timezone.now().timestamp())
        payload = {
            "masterID": "NO-MASTER",
            "timestamp": ts,
            "status": "alive",
            "smoke": 5,
            "slaves": [
                {
                    "deviceID": "SLAVE-OK",
                    "timestamp": ts,
                    "status": "alive",
                    "smoke": 200,
                }
            ],
        }
        process_payload(payload)
        # No telemetry should be created because master is unknown
        self.assertFalse(Telemetry.objects.filter(device=self.slave_ok).exists())

    def test_legacy_single_device_ingestion(self):
        # Single device payload for master
        ts = int(timezone.now().timestamp())
        payload = {
            "deviceID": "MASTER-ING",
            "timestamp": ts,
            "status": "alive",
            "smoke": 80,
        }
        process_payload(payload)
        # Smoke>threshold persists telemetry
        self.assertTrue(
            Telemetry.objects.filter(device=self.master, smoke_level__gte=80).exists()
        )
