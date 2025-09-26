from rest_framework.test import APITestCase
from rest_framework import status


class DeviceOwnershipTests(APITestCase):
    def setUp(self):
        r = self.client.post(
            "/auth/register",
            {"email": "a@example.com", "password": "Passw0rd!"},
            format="json",
        )
        r = self.client.post(
            "/auth/login",
            {"email": "a@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.token_a = r.data["access"]
        r = self.client.post(
            "/auth/register",
            {"email": "b@example.com", "password": "Passw0rd!"},
            format="json",
        )
        r = self.client.post(
            "/auth/login",
            {"email": "b@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.token_b = r.data["access"]

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
