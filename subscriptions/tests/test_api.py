from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from devices.models import Device
from subscriptions.enums import DeviceSubscriptionStatus
from subscriptions.models import DeviceSubscription


class SubscriptionApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="Passw0rd!",
        )
        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            password="Passw0rd!",
        )
        self.device = Device.objects.create(
            user=self.user,
            hardware_identifier="DEV-001",
            device_name="HQ Sensor",
        )
        start = timezone.now() - timedelta(days=45)
        cycle_end = start + timedelta(days=30)
        self.subscription = DeviceSubscription.objects.create(
            device=self.device,
            monthly_amount=Decimal("500.00"),
            status=DeviceSubscriptionStatus.ACTIVE,
            billing_anchor=start,
            last_paid_through=cycle_end,
            next_due_at=cycle_end,
        )

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def test_user_can_list_own_subscriptions(self):
        self.auth(self.user)
        url = reverse("user-subscriptions-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = response.data
        items = (
            payload.get("results", payload) if isinstance(payload, dict) else payload
        )
        self.assertGreaterEqual(len(items), 1)
        hardware_ids = [item["device"]["hardware_identifier"] for item in items]
        self.assertIn("DEV-001", hardware_ids)

    @patch("subscriptions.services.initiate_payment_for_charge")
    def test_user_topup_creates_charge(self, mock_initiate):
        mock_initiate.return_value = type(
            "Txn",
            (),
            {"checkout_url": "https://pay"},
        )
        self.auth(self.user)
        url = reverse(
            "user-subscriptions-topup",
            args=[self.subscription.pk],
        )
        response = self.client.post(
            url,
            {"months": 2},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        payload = response.data
        self.assertIn("charge", payload)
        self.assertEqual(payload["charge"]["cycles"], 2)
        mock_initiate.assert_called_once()

    def test_admin_can_record_manual_payment(self):
        self.auth(self.superuser)
        url = reverse(
            "admin-subscriptions-manual-payment",
            args=[self.subscription.pk],
        )
        response = self.client.post(
            url,
            {"months": 1, "note": "cash"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.status,
            DeviceSubscriptionStatus.ACTIVE,
        )
        self.assertIsNone(self.subscription.grace_expires_at)
