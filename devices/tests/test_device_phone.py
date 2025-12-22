from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from devices.constants import DeviceConfigurationPublishError
from devices.models import Device
from products.models import Package, Order, OrderFulfillment
from products.enums import OrderStatus


def create_fulfillment(user, hid, role="master"):
    """Helper to create order fulfillment for device registration."""
    package, _ = Package.objects.get_or_create(
        name="TestPackage",
        defaults={
            "min_quantity": 1,
            "max_quantity": 5,
            "price_per_device": Decimal("100.00"),
            "mrf": Decimal("10.00"),
        },
    )
    order = Order.objects.create(
        user=user,
        package=package,
        quantity=1,
        amount=Decimal("100.00"),
        order_status=OrderStatus.PAID,
    )
    OrderFulfillment.objects.create(
        order=order,
        hardware_identifier=hid,
        device_role=role,
    )
    return order


class DevicePhoneAssignmentTests(APITestCase):
    def setUp(self):
        # Create user and authenticate directly (bypasses OTP requirement)
        User = get_user_model()
        self.user = User.objects.create_user(
            email="owner@example.com", password="Passw0rd!"
        )
        self.client.force_authenticate(user=self.user)

    def _register_device(self) -> Device:
        # Create fulfillment before device registration
        create_fulfillment(self.user, "DEV-PHONE")
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
