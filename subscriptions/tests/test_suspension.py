from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from accounts.models import User
from devices.models import Device
from subscriptions.models import DeviceSubscription, SubscriptionCharge
from subscriptions.enums import DeviceSubscriptionStatus, SubscriptionChargeStatus
from subscriptions import services


class SubscriptionSuspensionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("test@example.com", "password")
        self.device = Device.objects.create(
            user=self.user,
            hardware_identifier="TEST-DEV-001",
            device_name="Test Device",
        )
        self.subscription = DeviceSubscription.objects.create(
            device=self.device,
            monthly_amount=Decimal("500.00"),
            status=DeviceSubscriptionStatus.GRACE,
            billing_anchor=timezone.now(),
            last_paid_through=timezone.now(),
            next_due_at=timezone.now(),
        )

    def test_subscription_suspension_after_grace_period(self):
        """
        Test that a subscription is suspended when the grace period expires
        and there is a pending charge.
        """
        # 1. Setup: Grace period expired yesterday
        self.subscription.grace_expires_at = timezone.now() - timedelta(days=1)
        self.subscription.save()

        # Create a pending charge (requirement for suspension in services.py)
        SubscriptionCharge.objects.create(
            subscription=self.subscription,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
            amount=Decimal("500.00"),
            status=SubscriptionChargeStatus.PENDING,
        )

        # Verify initial state
        self.assertEqual(self.subscription.status, DeviceSubscriptionStatus.GRACE)
        # Even in grace, if expired, is_active_for_user should be False (based on model logic)
        # But the status field itself is updated by the task.

        # 2. Run the suspension task/service
        updated_count = services.suspend_overdue_subscriptions()

        # 3. Verify results
        self.subscription.refresh_from_db()

        self.assertEqual(updated_count, 1)
        self.assertEqual(self.subscription.status, DeviceSubscriptionStatus.SUSPENDED)
        self.assertFalse(self.subscription.is_active_for_user)

    def test_subscription_not_suspended_during_grace_period(self):
        """
        Test that a subscription is NOT suspended if the grace period
        has not yet expired.
        """
        # 1. Setup: Grace period expires tomorrow
        self.subscription.grace_expires_at = timezone.now() + timedelta(days=1)
        self.subscription.save()

        SubscriptionCharge.objects.create(
            subscription=self.subscription,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(days=30),
            amount=Decimal("500.00"),
            status=SubscriptionChargeStatus.PENDING,
        )

        # 2. Run the suspension task/service
        updated_count = services.suspend_overdue_subscriptions()

        # 3. Verify results
        self.subscription.refresh_from_db()

        self.assertEqual(updated_count, 0)
        self.assertEqual(self.subscription.status, DeviceSubscriptionStatus.GRACE)
        self.assertTrue(self.subscription.is_active_for_user)
