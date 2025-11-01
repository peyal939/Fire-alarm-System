from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from firestations.models import Division, District, FireStation


class FireStationAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="user@example.com", password="pass1234"
        )
        cls.division = Division.objects.create(
            name_en="Dhaka Division", name_bn="ঢাকা বিভাগ"
        )
        cls.district = District.objects.create(
            division=cls.division,
            name_en="Dhaka District",
            name_bn="ঢাকা জেলা",
        )
        cls.station = FireStation.objects.create(
            district=cls.district,
            name_en="Dhaka Fire Station",
            name_bn="ঢাকা ফায়ার স্টেশন",
            serial=1,
            contact_numbers="01711111111|01722222222",
            contact_text="Emergency contact",
        )
        cls.station_two = FireStation.objects.create(
            district=cls.district,
            name_en="Gulshan Fire Station",
            name_bn="গুলশান ফায়ার স্টেশন",
            serial=2,
            contact_numbers="01799999999",
        )

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("firestation-list")

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_firestations(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 2)
        first = payload["results"][0]
        self.assertIn("division_en", first)
        self.assertIn("contact_number_list", first)
        self.assertTrue(first["contact_number_list"])

    def test_search_bangla_name(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url, {"search": "গুলশান"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json().get("results", [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name_en"], "Gulshan Fire Station")

    def test_filter_by_division_parameter(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url, {"division": "Dhaka"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json().get("results", [])
        self.assertTrue(any(r["name_en"] == "Dhaka Fire Station" for r in results))

    def test_pagination_limit(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.url, {"limit": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(len(payload.get("results", [])), 1)
        self.assertIn("count", payload)
