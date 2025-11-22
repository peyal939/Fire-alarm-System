from decimal import Decimal

from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from products.models import Order, Package
from subscriptions.models import DeviceSubscription
from devices.models import Device


class DeviceOwnershipTests(APITestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            email="a@example.com", password="Passw0rd!"
        )
        self.user_b = User.objects.create_user(
            email="b@example.com", password="Passw0rd!"
        )
        self.token_a = str(RefreshToken.for_user(self.user_a).access_token)
        self.token_b = str(RefreshToken.for_user(self.user_b).access_token)

    def test_owner_cannot_see_others_device(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEVX",
                "device_name": "MyDevice",
                "latitude": 23.78,
                "longitude": 90.41,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        dev_id = r.data["id"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_b}")
        r = self.client.get("/devices/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data
        items = (
            data["results"] if isinstance(data, dict) and "results" in data else data
        )
        ids = [d["id"] for d in items]
        self.assertNotIn(dev_id, ids)

        r = self.client.get(f"/devices/{dev_id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_device_registration_creates_subscription(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEV-SUB-1",
                "device_name": "Subscription Sensor",
                "latitude": 23.79,
                "longitude": 90.42,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        device_id = response.data["id"]
        subscription = DeviceSubscription.objects.get(device_id=device_id)
        self.assertEqual(subscription.status, DeviceSubscription.Status.ACTIVE)

    def test_device_registration_with_order_links_subscription(self):
        user = self.user_a
        package = Package.objects.create(
            name="Starter",
            min_quantity=1,
            max_quantity=5,
            price_per_device=Decimal("2500.00"),
            mrf=Decimal("500.00"),
        )
        order = Order.objects.create(
            user=user,
            package=package,
            number_of_master_devices=1,
            number_of_slave_devices=0,
            quantity=1,
            amount=Decimal("2500.00"),
            order_status=Order.Status.PAID,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEV-ORDER-1",
                "device_name": "Order Linked Sensor",
                "latitude": 23.75,
                "longitude": 90.40,
                "originating_order_id": order.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data.get("originating_order_id"), order.id)

        device_id = response.data["id"]
        subscription = DeviceSubscription.objects.get(device_id=device_id)
        self.assertEqual(subscription.originating_order_id, order.id)

        order.refresh_from_db()
        self.assertEqual(order.assigned_devices, 1)

    def test_register_master_rejects_when_order_master_limit_reached(self):
        package = Package.objects.create(
            name="Starter",
            min_quantity=1,
            max_quantity=5,
            price_per_device=Decimal("2500.00"),
            mrf=Decimal("500.00"),
        )
        order = Order.objects.create(
            user=self.user_a,
            package=package,
            number_of_master_devices=1,
            number_of_slave_devices=2,
            quantity=3,
            amount=Decimal("7500.00"),
            order_status=Order.Status.PAID,
        )
        Device.objects.create(
            user=self.user_a,
            hardware_identifier="MASTER-EXIST",
            device_role=Device.DeviceRole.MASTER,
            originating_order=order,
            latitude=Decimal("23.70"),
            longitude=Decimal("90.40"),
            created_by=self.user_a,
        )
        order.assigned_devices = 1
        order.save(update_fields=["assigned_devices"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "MASTER-OVERFLOW",
                "device_name": "Overflow Master",
                "latitude": 23.75,
                "longitude": 90.41,
                "device_role": "master",
                "originating_order_id": order.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        errors = response.data.get("non_field_errors", [])
        self.assertTrue(any("master device slots" in str(err) for err in errors))

    def test_auto_assignment_master_limit_enforced(self):
        package = Package.objects.create(
            name="Starter",
            min_quantity=1,
            max_quantity=5,
            price_per_device=Decimal("2500.00"),
            mrf=Decimal("500.00"),
        )
        order = Order.objects.create(
            user=self.user_a,
            package=package,
            number_of_master_devices=2,
            number_of_slave_devices=3,
            quantity=5,
            amount=Decimal("12500.00"),
            order_status=Order.Status.PAID,
        )
        Device.objects.create(
            user=self.user_a,
            hardware_identifier="MASTER-A",
            device_role=Device.DeviceRole.MASTER,
            originating_order=order,
            latitude=Decimal("23.70"),
            longitude=Decimal("90.40"),
            created_by=self.user_a,
        )
        Device.objects.create(
            user=self.user_a,
            hardware_identifier="MASTER-B",
            device_role=Device.DeviceRole.MASTER,
            originating_order=order,
            latitude=Decimal("23.71"),
            longitude=Decimal("90.41"),
            created_by=self.user_a,
        )
        order.assigned_devices = 2
        order.save(update_fields=["assigned_devices"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "MASTER-C",
                "device_name": "Overflow Master",
                "latitude": 23.75,
                "longitude": 90.41,
                "device_role": "master",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("master device slots", response.data.get("detail", ""))

    def test_register_slave_rejects_when_order_slave_limit_reached(self):
        package = Package.objects.create(
            name="Starter",
            min_quantity=1,
            max_quantity=5,
            price_per_device=Decimal("2500.00"),
            mrf=Decimal("500.00"),
        )
        order = Order.objects.create(
            user=self.user_a,
            package=package,
            number_of_master_devices=1,
            number_of_slave_devices=1,
            quantity=3,
            amount=Decimal("7500.00"),
            order_status=Order.Status.PAID,
        )
        master = Device.objects.create(
            user=self.user_a,
            hardware_identifier="MASTER-BASE",
            device_role=Device.DeviceRole.MASTER,
            originating_order=order,
            latitude=Decimal("23.71"),
            longitude=Decimal("90.41"),
            created_by=self.user_a,
        )
        Device.objects.create(
            user=self.user_a,
            hardware_identifier="SLAVE-EXIST",
            device_role=Device.DeviceRole.SLAVE,
            master=master,
            originating_order=order,
            latitude=Decimal("23.72"),
            longitude=Decimal("90.42"),
            created_by=self.user_a,
        )
        order.assigned_devices = 2
        order.save(update_fields=["assigned_devices"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        response = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "SLAVE-OVERFLOW",
                "device_name": "Overflow Slave",
                "latitude": 23.76,
                "longitude": 90.45,
                "device_role": "slave",
                "master_id": master.id,
                "originating_order_id": order.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        errors = response.data.get("non_field_errors", [])
        self.assertTrue(any("slave device slots" in str(err) for err in errors))
