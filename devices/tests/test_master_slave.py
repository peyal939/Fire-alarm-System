from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from devices.models import Device
from products.models import Package, Order, OrderFulfillment
from products.enums import OrderStatus


def get_items(data):
    return data["results"] if isinstance(data, dict) and "results" in data else data


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


class MasterSlaveRegistrationAndTreeTests(APITestCase):
    def setUp(self):
        # Create two users A and B and authenticate directly (bypasses OTP requirement)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user_a = User.objects.create_user(
            email="msa@example.com", password="Passw0rd!"
        )
        self.user_b = User.objects.create_user(
            email="msb@example.com", password="Passw0rd!"
        )

    def test_master_slave_registration_and_tree(self):
        # Login as A
        self.client.force_authenticate(user=self.user_a)

        # Create fulfillments for all devices that will be registered
        create_fulfillment(self.user_a, "MSTR-1", role="master")
        create_fulfillment(self.user_a, "SLV-FAIL", role="slave")
        create_fulfillment(self.user_a, "SLV-1", role="slave")
        create_fulfillment(self.user_a, "MSTR-ERR", role="master")
        create_fulfillment(self.user_a, "SLV-2", role="slave")
        create_fulfillment(self.user_b, "SLV-B", role="slave")

        # 1) Register a master (no master_id required)
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "MSTR-1",
                "device_name": "Master One",
                "latitude": 23.78,
                "longitude": 90.41,
                # device_role omitted => defaults to master
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        master_id = r.data["id"]
        self.assertEqual(r.data.get("device_role"), Device.DeviceRole.MASTER)
        self.assertIsNone(r.data.get("master_id"))

        # 2) Registering a slave without master_id should fail
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "SLV-FAIL",
                "device_name": "Slave Fail",
                "latitude": 23.71,
                "longitude": 90.42,
                "device_role": Device.DeviceRole.SLAVE,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

        # 3) Register a valid slave under the master
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "SLV-1",
                "device_name": "Slave One",
                "latitude": 23.71,
                "longitude": 90.42,
                "device_role": Device.DeviceRole.SLAVE,
                "master_id": master_id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        slave1_id = r.data["id"]
        self.assertEqual(r.data.get("device_role"), Device.DeviceRole.SLAVE)
        self.assertEqual(r.data.get("master_id"), master_id)

        # 4) Registering MASTER with master_id should fail
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "MSTR-ERR",
                "device_name": "Master Err",
                "latitude": 23.7,
                "longitude": 90.4,
                "device_role": Device.DeviceRole.MASTER,
                "master_id": master_id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

        # 5) Attempt to register a slave using another slave as master should fail
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "SLV-2",
                "device_name": "Slave Two",
                "latitude": 23.72,
                "longitude": 90.43,
                "device_role": Device.DeviceRole.SLAVE,
                "master_id": slave1_id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

        # 6) Tree endpoint should return master with nested slaves for user A
        r = self.client.get("/devices/tree/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        masters = get_items(r.data)
        # Find our master
        m = next((d for d in masters if d["id"] == master_id), None)
        self.assertIsNotNone(m)
        self.assertEqual(m.get("device_role"), Device.DeviceRole.MASTER)
        s_ids = [s["id"] for s in m.get("slaves", [])]
        self.assertIn(slave1_id, s_ids)

        # 7) User B cannot register a slave under A's master (ownership enforced)
        self.client.force_authenticate(user=self.user_b)
        r = self.client.post(
            "/devices/register/",
            {
                "hardware_identifier": "SLV-B",
                "device_name": "Slave B",
                "latitude": 23.73,
                "longitude": 90.44,
                "device_role": Device.DeviceRole.SLAVE,
                "master_id": master_id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

        # 8) Tree for B should be empty
        r = self.client.get("/devices/tree/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_items(r.data)), 0)
