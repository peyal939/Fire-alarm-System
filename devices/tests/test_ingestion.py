from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from devices.enums import AlertStatus
from devices.models import Device, Alert
from devices import services
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


class IngestionAndAlertsTests(APITestCase):
    def setUp(self):
        # Create user and authenticate directly (bypasses OTP requirement)
        User = get_user_model()
        self.user = User.objects.create_user(
            email="c@example.com", password="Passw0rd!"
        )
        self.client.force_authenticate(user=self.user)

        # Create fulfillment before device registration
        create_fulfillment(self.user, "DEVY")
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
            Alert.objects.filter(device=self.device, status=AlertStatus.OPEN).count(),
            2,
        )
        ts2 = timezone.now()
        services.ingest_telemetry(
            self.device, smoke_level=0, device_status="alive", timestamp=ts2
        )
        self.assertEqual(
            Alert.objects.filter(device=self.device, status=AlertStatus.OPEN).count(),
            0,
        )

    def test_unknown_device_ignored(self):
        ts = timezone.now()
        ok = services.ingest_by_hardware_identifier(
            "UNKNOWN", smoke_level=10, device_status="alive", timestamp=ts
        )
        self.assertFalse(ok)
