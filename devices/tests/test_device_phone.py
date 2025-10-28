from unittest import mock

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from devices.constants import DeviceConfigurationPublishError
from devices.models import Device


class DevicePhoneAssignmentTests(APITestCase):
    def setUp(self):
        self.client.post(
            "/auth/register",
            {"email": "owner@example.com", "password": "Passw0rd!"},
            format="json",
        )
        login = self.client.post(
            "/auth/login",
            {"email": "owner@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.token = login.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def _register_device(self) -> Device:
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEV-PHONE",
                "device_name": "Phone Target",
                "latitude": 23.78,
                "longitude": 90.41,
            },
            format="json",
        )
        self.assertIn(
            response.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED)
        )
        device_id = response.data["id"]
        return Device.objects.get(id=device_id)

    def test_requires_online_device(self):
        device = self._register_device()
        with mock.patch(
            "devices.services.publish_device_phone_assignment"
        ) as publish_mock:
            response = self.client.post(
                f"/devices/{device.id}/phone/",
                {"phone_number": "01778043119"},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        publish_mock.assert_not_called()
        device.refresh_from_db()
        self.assertIsNone(device.phone_number)

    def test_assign_phone_success(self):
        device = self._register_device()
        Device.objects.filter(id=device.id).update(last_seen=timezone.now())

        with mock.patch(
            "devices.services.publish_device_phone_assignment"
        ) as publish_mock:
            publish_mock.return_value = None
            response = self.client.post(
                f"/devices/{device.id}/phone/",
                {"phone_number": "01778043119"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        device.refresh_from_db()
        self.assertEqual(device.phone_number, "+8801778043119")
        self.assertIsNotNone(device.phone_number_updated_at)
        publish_mock.assert_called_once()
        args, kwargs = publish_mock.call_args
        self.assertEqual(args[0], device)
        self.assertEqual(kwargs["phone_number"], "+8801778043119")
        self.assertEqual(kwargs, {"phone_number": "+8801778043119"})

    def test_invalid_phone_returns_400(self):
        device = self._register_device()
        Device.objects.filter(id=device.id).update(last_seen=timezone.now())

        response = self.client.post(
            f"/devices/{device.id}/phone/",
            {"phone_number": "12345"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid bangladeshi", str(response.data["phone_number"]).lower())

    def test_mqtt_failure_rolls_back(self):
        device = self._register_device()
        Device.objects.filter(id=device.id).update(last_seen=timezone.now())

        with mock.patch(
            "devices.services.publish_device_phone_assignment",
            side_effect=DeviceConfigurationPublishError("DEV-PHONE", "boom"),
        ):
            response = self.client.post(
                f"/devices/{device.id}/phone/",
                {"phone_number": "01778043119"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        device.refresh_from_db()
        self.assertIsNone(device.phone_number)
        self.assertIsNone(device.phone_number_updated_at)
