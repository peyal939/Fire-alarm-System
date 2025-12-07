from __future__ import annotations

from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from devices.models import Device
from products.models import Package, Order
from subscriptions.models import DeviceSubscription, SubscriptionCharge
from subscriptions.enums import SubscriptionChargeStatus, DeviceSubscriptionStatus
from subscriptions import services


class ManualRetryTests(APITestCase):
    """Tests for manual payment retry functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
        )
        self.package = Package.objects.create(
            name="Test Package",
            min_quantity=1,
            max_quantity=10,
            price_per_device=Decimal("1000.00"),
            mrf=Decimal("100.00"),
        )
        self.order = Order.objects.create(
            user=self.user,
            package=self.package,
            quantity=1,
            amount=Decimal("1100.00"),
            order_status="paid",
        )
        self.device = Device.objects.create(
            hardware_identifier="TEST-001",
            user=self.user,
            originating_order=self.order,
            package=self.package,
        )
        self.subscription = DeviceSubscription.objects.create(
            device=self.device,
            originating_order=self.order,
            monthly_amount=Decimal("100.00"),
            status=DeviceSubscriptionStatus.GRACE,
            billing_anchor=timezone.now() - timedelta(days=30),
            last_paid_through=timezone.now() - timedelta(days=30),
            next_due_at=timezone.now() - timedelta(days=30),
        )
        self.failed_charge = SubscriptionCharge.objects.create(
            subscription=self.subscription,
            period_start=timezone.now() - timedelta(days=30),
            period_end=timezone.now(),
            amount=Decimal("100.00"),
            status=SubscriptionChargeStatus.FAILED,
            failure_reason="Payment declined",
        )

    @patch("subscriptions.services.initiate_payment_for_charge")
    def test_user_retry_failed_payment(self, mock_initiate):
        """Test user can retry failed payment."""
        mock_txn = MagicMock()
        mock_txn.pk = 123
        mock_txn.checkout_url = "https://payment.example.com/checkout"
        mock_initiate.return_value = mock_txn

        self.client.force_authenticate(user=self.user)
        url = reverse(
            "user-subscriptions-retry",
            kwargs={"pk": self.subscription.pk}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("checkout_url", response.data)
        self.assertEqual(response.data["checkout_url"], "https://payment.example.com/checkout")

        # Check retry count incremented
        self.failed_charge.refresh_from_db()
        self.assertEqual(self.failed_charge.retry_count, 1)
        self.assertIsNotNone(self.failed_charge.last_retry_at)

    @patch("subscriptions.services.initiate_payment_for_charge")
    def test_admin_retry_payment(self, mock_initiate):
        """Test admin can retry payment for any subscription."""
        mock_txn = MagicMock()
        mock_txn.pk = 456
        mock_txn.checkout_url = "https://payment.example.com/admin-checkout"
        mock_initiate.return_value = mock_txn

        self.client.force_authenticate(user=self.admin)
        url = reverse(
            "admin-subscriptions-retry-payment",
            kwargs={"pk": self.subscription.pk}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)
        self.assertIn("retry", response.data["message"].lower())

    def test_retry_no_failed_charge(self):
        """Test retry fails when no failed charge exists."""
        # Mark charge as paid
        self.failed_charge.status = SubscriptionChargeStatus.PAID
        self.failed_charge.save()

        self.client.force_authenticate(user=self.user)
        url = reverse(
            "user-subscriptions-retry",
            kwargs={"pk": self.subscription.pk}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No failed", response.data["detail"])

    @patch("subscriptions.services.initiate_payment_for_charge")
    def test_retry_payment_gateway_failure(self, mock_initiate):
        """Test retry handles gateway failure gracefully."""
        mock_initiate.return_value = None  # Gateway failed

        self.client.force_authenticate(user=self.user)
        url = reverse(
            "user-subscriptions-retry",
            kwargs={"pk": self.subscription.pk}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_retry_other_user_subscription_denied(self):
        """Test user cannot retry another user's subscription."""
        other_user = User.objects.create_user(
            email="other@example.com",
            password="otherpass123",
        )
        self.client.force_authenticate(user=other_user)

        url = reverse(
            "user-subscriptions-retry",
            kwargs={"pk": self.subscription.pk}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("subscriptions.services.initiate_payment_for_charge")
    def test_multiple_retries_tracked(self, mock_initiate):
        """Test multiple retries are tracked correctly."""
        mock_txn = MagicMock()
        mock_txn.pk = 789
        mock_txn.checkout_url = "https://payment.example.com/checkout"
        mock_initiate.return_value = mock_txn

        self.client.force_authenticate(user=self.user)
        url = reverse(
            "user-subscriptions-retry",
            kwargs={"pk": self.subscription.pk}
        )

        # First retry
        self.client.post(url)
        self.failed_charge.refresh_from_db()
        first_retry_time = self.failed_charge.last_retry_at
        self.assertEqual(self.failed_charge.retry_count, 1)

        # Second retry
        self.client.post(url)
        self.failed_charge.refresh_from_db()
        self.assertEqual(self.failed_charge.retry_count, 2)
        self.assertGreater(self.failed_charge.last_retry_at, first_retry_time)

    def test_unauthenticated_retry_denied(self):
        """Test unauthenticated retry requests are denied."""
        url = reverse(
            "user-subscriptions-retry",
            kwargs={"pk": self.subscription.pk}
        )
        response = self.client.post(url)

        # DRF returns 403 Forbidden for unauthenticated requests by default
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class RetryFieldsTests(TestCase):
    """Tests for retry tracking fields on SubscriptionCharge."""

    def test_default_retry_count(self):
        """Test retry_count defaults to 0."""
        user = User.objects.create_user(email="test@example.com", password="test")
        package = Package.objects.create(
            name="Test",
            min_quantity=1,
            max_quantity=10,
            price_per_device=Decimal("100.00"),
        )
        device = Device.objects.create(
            hardware_identifier="DEV-001",
            user=user,
            package=package,
        )
        subscription = DeviceSubscription.objects.create(
            device=device,
            monthly_amount=Decimal("10.00"),
            billing_anchor=timezone.now(),
            last_paid_through=timezone.now(),
            next_due_at=timezone.now() + timedelta(days=30),
        )
        charge = SubscriptionCharge.objects.create(
            subscription=subscription,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
            amount=Decimal("10.00"),
        )

        self.assertEqual(charge.retry_count, 0)
        self.assertIsNone(charge.last_retry_at)
