from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from accounts.models import User
from devices.models import Device
from devices.serializers import DeviceSerializer
from devices.services import ingest_telemetry
from subscriptions.models import DeviceSubscription
from subscriptions.enums import DeviceSubscriptionStatus


class SubscriptionEnforcementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("user@example.com", "password")
        self.admin = User.objects.create_superuser("admin@example.com", "password")

        self.device = Device.objects.create(
            user=self.user,
            hardware_identifier="TEST-DEV-ENFORCE",
            device_name="Test Device",
            status="alive",
            last_seen=timezone.now(),
        )

        self.subscription = DeviceSubscription.objects.create(
            device=self.device,
            status=DeviceSubscriptionStatus.ACTIVE,
            billing_anchor=timezone.now(),
            last_paid_through=timezone.now() + timedelta(days=30),
            next_due_at=timezone.now() + timedelta(days=30),
        )

        self.factory = APIRequestFactory()

    @patch("notifications.services.FCMService.send_alert_notification")
    def test_notification_blocked_when_suspended(self, mock_send_alert):
        """Test that smoke alerts do NOT trigger notifications if suspended."""
        # 1. Suspend the subscription
        self.subscription.status = DeviceSubscriptionStatus.SUSPENDED
        # Ensure grace is expired so is_active_for_user returns False
        self.subscription.grace_expires_at = timezone.now() - timedelta(days=1)
        self.subscription.save()

        # 2. Ingest high smoke (should trigger alert logic)
        ingest_telemetry(
            device=self.device,
            smoke_level=200,  # > threshold 50
            device_status="alive",
            timestamp=timezone.now(),
        )

        # 3. Verify notification service was NOT called
        mock_send_alert.assert_not_called()

    @patch("notifications.services.FCMService.send_alert_notification")
    def test_notification_sent_when_active(self, mock_send_alert):
        """Test that smoke alerts DO trigger notifications if active."""
        # 1. Ensure active
        self.subscription.status = DeviceSubscriptionStatus.ACTIVE
        self.subscription.save()

        # 2. Ingest high smoke
        ingest_telemetry(
            device=self.device,
            smoke_level=200,
            device_status="alive",
            timestamp=timezone.now(),
        )

        # 3. Verify notification service WAS called
        mock_send_alert.assert_called_once()

    def test_serializer_masks_data_for_user_when_suspended(self):
        """Test that normal users see 'suspended' status and masked data."""
        # 1. Suspend
        self.subscription.status = DeviceSubscriptionStatus.SUSPENDED
        self.subscription.grace_expires_at = timezone.now() - timedelta(days=1)
        self.subscription.save()

        # 2. Serialize with user context
        request = self.factory.get("/")
        request.user = self.user
        serializer = DeviceSerializer(self.device, context={"request": request})
        data = serializer.data

        # 3. Verify masking
        self.assertEqual(data["status"], "suspended")
        self.assertEqual(data["effective_status"], "suspended")
        self.assertIsNone(data["last_seen"])
        self.assertIsNone(data["mesh_alert"])
        self.assertFalse(data["online"])

    def test_serializer_shows_data_for_admin_when_suspended(self):
        """Test that admins see REAL data even if suspended."""
        # 1. Suspend
        self.subscription.status = DeviceSubscriptionStatus.SUSPENDED
        self.subscription.grace_expires_at = timezone.now() - timedelta(days=1)
        self.subscription.save()

        # 2. Serialize with ADMIN context
        request = self.factory.get("/")
        request.user = self.admin
        serializer = DeviceSerializer(self.device, context={"request": request})
        data = serializer.data

        # 3. Verify NO masking
        self.assertEqual(data["status"], "alive")  # Real status from setUp
        self.assertIsNotNone(data["last_seen"])
        # online might be True or False depending on last_seen freshness,
        # but it shouldn't be forced False by suspension logic alone if fresh.
        # In setUp we set last_seen=now, so it should be online.
        self.assertTrue(data["online"])
