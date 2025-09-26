from rest_framework.test import APITestCase
from rest_framework import status


class AuthFlowTests(APITestCase):
    def test_register_login_me(self):
        resp = self.client.post(
            "/auth/register",
            {
                "email": "u1@example.com",
                "password": "Passw0rd!",
                "phone_number": "0123456789",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        resp = self.client.post(
            "/auth/login",
            {"email": "u1@example.com", "password": "Passw0rd!"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        access = resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = self.client.get("/auth/me")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["email"], "u1@example.com")
