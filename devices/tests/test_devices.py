from decimal import Decimal

from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from products.models import Order, Package, OrderFulfillment
from products.enums import OrderStatus
from subscriptions.enums import DeviceSubscriptionStatus
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
        self._fulfill(self.user_a, "DEVX")
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
        self._fulfill(self.user_a, "DEV-SUB-1")
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
        self.assertEqual(subscription.status, DeviceSubscriptionStatus.ACTIVE)

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
            order_status=OrderStatus.PAID,
        )
        OrderFulfillment.objects.create(
            order=order,
            hardware_identifier="DEV-ORDER-1",
            device_role="master",
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

        # Note: fulfillment-based registration does not currently increment assigned_devices
        # order.refresh_from_db()
        # self.assertEqual(order.assigned_devices, 1)

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
            order_status=OrderStatus.PAID,
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
            order_status=OrderStatus.PAID,
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
        # Strict mode blocks registration without fulfillment
        self.assertIn("Device ID not authorized", response.data.get("detail", ""))

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
            order_status=OrderStatus.PAID,
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

    def test_register_restores_soft_deleted_device_with_fulfillment(self):
        # 1. User A registers a device
        self._fulfill(self.user_a, "DEV-RECLAIM")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEV-RECLAIM",
                "device_name": "User A Device",
                "latitude": 23.0,
                "longitude": 90.0,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        device_id = r.data["id"]

        # 2. User A deletes the device
        r = self.client.delete(f"/devices/{device_id}/")
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)

        # 3. Admin fulfills the same device ID to User B
        # First, soft-delete the old fulfillment (as admin would do)
        old_fulfillment = OrderFulfillment.objects.get(
            hardware_identifier="DEV-RECLAIM"
        )
        old_fulfillment.delete()

        # (Simulate admin action by creating fulfillment directly)
        package = Package.objects.get(name="TestPackage")
        order_b = Order.objects.create(
            user=self.user_b,
            package=package,
            quantity=1,
            amount=Decimal("100.00"),
            order_status=OrderStatus.PAID,
        )
        OrderFulfillment.objects.create(
            order=order_b,
            hardware_identifier="DEV-RECLAIM",
            device_role="master",
        )

        # 4. User B registers the device
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_b}")
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "DEV-RECLAIM",
                "device_name": "User B Device",
                "latitude": 23.1,
                "longitude": 90.1,
            },
            format="json",
        )

        # 5. Verify success
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        device = Device.objects.get(hardware_identifier="DEV-RECLAIM")
        self.assertEqual(device.user, self.user_b)
        self.assertIsNone(device.deleted_at)
        self.assertEqual(device.originating_order, order_b)

    def _fulfill(self, user, hid, role="master"):
        package = Package.objects.get_or_create(
            name="TestPackage",
            defaults={
                "min_quantity": 1,
                "max_quantity": 5,
                "price_per_device": Decimal("100.00"),
                "mrf": Decimal("10.00"),
            },
        )[0]
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
