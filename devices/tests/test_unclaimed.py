from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import User
from devices.models import Device
from django.utils import timezone

from products.models import Order, OrderFulfillment, Package
from products.enums import OrderStatus

from decimal import Decimal

class UnclaimedDevicesTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="password")
        self.token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        
        self.package = Package.objects.create(
            name="Test Package",
            min_quantity=1,
            max_quantity=10,
            price_per_device=Decimal("1000.00"),
            mrf=Decimal("100.00")
        )

    def test_unclaimed_devices_list(self):
        # 1. No devices
        response = self.client.get("/devices/unclaimed/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

        # 2. Create a registered device (should not appear)
        Device.objects.create(
            user=self.user,
            hardware_identifier="REG-1",
            registered_at=timezone.now()
        )
        response = self.client.get("/devices/unclaimed/")
        self.assertEqual(len(response.data), 0)

        # 3. Create an fulfilled order (unclaimed)
        order = Order.objects.create(
            user=self.user,
            package=self.package,
            quantity=1,
            amount=Decimal("1000.00"),
            order_status=OrderStatus.PAID
        )
        OrderFulfillment.objects.create(
            order=order,
            hardware_identifier="UNCLAIMED-1",
            device_role="master"
        )
        
        response = self.client.get("/devices/unclaimed/")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["hardware_identifier"], "UNCLAIMED-1")
        # Verify default location is returned for unclaimed device (as floats)
        self.assertEqual(response.data[0]["latitude"], 23.810300)
        self.assertEqual(response.data[0]["longitude"], 90.412500)
        # Verify ID is present and negative (to avoid collision)
        self.assertIn("id", response.data[0])
        # We expect negative ID for unclaimed devices
        self.assertTrue(response.data[0]["id"] < 0)

    def test_cannot_see_others_unclaimed(self):
        other_user = User.objects.create_user(email="other@example.com", password="password")
        order = Order.objects.create(
            user=other_user,
            package=self.package,
            quantity=1,
            amount=Decimal("1000.00"),
            order_status=OrderStatus.PAID
        )
        OrderFulfillment.objects.create(
            order=order,
            hardware_identifier="OTHER-UNCLAIMED",
            device_role="master"
        )
        
        response = self.client.get("/devices/unclaimed/")
        self.assertEqual(len(response.data), 0)

    def test_register_fulfilled_device(self):
        # Create fulfilled order
        order = Order.objects.create(
            user=self.user,
            package=self.package,
            quantity=1,
            amount=Decimal("1000.00"),
            order_status=OrderStatus.PAID
        )
        fulfillment = OrderFulfillment.objects.create(
            order=order,
            hardware_identifier="FULFILLED-1",
            device_role="master"
        )

        # Register the device
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "FULFILLED-1",
                "device_name": "My Device",
                "latitude": 23.81,
                "longitude": 90.41,
                "device_role": "master"
            },
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify device created
        device = Device.objects.get(hardware_identifier="FULFILLED-1")
        self.assertEqual(device.user, self.user)
        self.assertEqual(device.originating_order, order)
        
        # Verify fulfillment marked as claimed
        fulfillment.refresh_from_db()
        self.assertTrue(fulfillment.is_claimed)

    def test_cannot_register_unauthorized_device(self):
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "UNKNOWN-1",
                "device_name": "My Device",
                "latitude": 23.81,
                "longitude": 90.41,
                "device_role": "master"
            },
            format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_device_resets_fulfillment(self):
        # Create fulfilled order
        order = Order.objects.create(
            user=self.user,
            package=self.package,
            quantity=1,
            amount=Decimal("1000.00"),
            order_status=OrderStatus.PAID
        )
        fulfillment = OrderFulfillment.objects.create(
            order=order,
            hardware_identifier="DEL-1",
            device_role="master"
        )

        # Register
        self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEL-1",
                "device_name": "My Device",
                "latitude": 23.81,
                "longitude": 90.41,
                "device_role": "master"
            },
            format="json"
        )
        
        fulfillment.refresh_from_db()
        self.assertTrue(fulfillment.is_claimed)
        
        device = Device.objects.get(hardware_identifier="DEL-1")
        
        # Delete
        self.client.delete(f"/devices/{device.id}/")
        
        fulfillment.refresh_from_db()
        self.assertFalse(fulfillment.is_claimed)
        
        # Should appear in unclaimed again
        response = self.client.get("/devices/unclaimed/")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["hardware_identifier"], "DEL-1")
