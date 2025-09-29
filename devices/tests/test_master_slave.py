from rest_framework.test import APITestCase
from rest_framework import status

from devices.models import Device


def get_items(data):
    return data["results"] if isinstance(data, dict) and "results" in data else data


class MasterSlaveRegistrationAndTreeTests(APITestCase):
    def setUp(self):
        # Create two users A and B
        r = self.client.post(
            "/auth/register",
            {"email": "msa@example.com", "password": "Passw0rd!"},
            format="json",
        )
        r = self.client.post(
            "/auth/login",
            {"email": "msa@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.token_a = r.data["access"]

        r = self.client.post(
            "/auth/register",
            {"email": "msb@example.com", "password": "Passw0rd!"},
            format="json",
        )
        r = self.client.post(
            "/auth/login",
            {"email": "msb@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.token_b = r.data["access"]

    def test_master_slave_registration_and_tree(self):
        # Login as A
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_a}")

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
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_b}")
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
