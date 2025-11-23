from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from devices.models import Device
from products.enums import OrderStatus
from products.models import Order, Package
from shurjopay.enums import PaymentTransactionStatus
from shurjopay.models import PaymentTransaction
from subscriptions import services
from subscriptions.enums import DeviceSubscriptionStatus, SubscriptionChargeStatus
from subscriptions.models import DeviceSubscription, SubscriptionCharge


class SubscriptionServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", "Passw0rd!")
        self.package = Package.objects.create(
            name="Starter",
            min_quantity=1,
            max_quantity=5,
            price_per_device=Decimal("2500.00"),
            mrf=Decimal("500.00"),
        )
        self.order = Order.objects.create(
            user=self.user,
            package=self.package,
            number_of_master_devices=1,
            number_of_slave_devices=0,
            quantity=1,
            amount=Decimal("2500.00"),
            order_status=OrderStatus.PAID,
        )
        self.device = Device.objects.create(
            user=self.user,
            hardware_identifier="DEV-001",
            device_name="HQ Sensor",
            originating_order=self.order,
        )
        activated = timezone.now() - timedelta(days=40)
        cycle_end = activated + timedelta(days=30)
        self.subscription = DeviceSubscription.objects.create(
            device=self.device,
            originating_order=self.order,
            monthly_amount=self.package.mrf,
            status=DeviceSubscriptionStatus.ACTIVE,
            billing_anchor=activated,
            last_paid_through=cycle_end,
            next_due_at=cycle_end,
        )

    @patch("subscriptions.services.shurjopay_services.initiate_payment")
    def test_create_charge_triggers_payment_and_grace(self, initiate_mock):
        initiate_mock.return_value = SimpleNamespace(
            checkout_url="https://pay.example/tx",
            sp_order_id="SP-123",
            customer_order_id="CUS-456",
        )
        now = self.subscription.next_due_at + timedelta(minutes=5)

        charge = services.create_charge_for_subscription(self.subscription, as_of=now)

        self.assertIsNotNone(charge)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DeviceSubscriptionStatus.GRACE)
        self.assertIsNotNone(charge.payment_transaction)
        self.assertEqual(
            charge.payment_transaction.status, PaymentTransactionStatus.REDIRECTED
        )
        initiate_mock.assert_called_once()

    def test_sync_charge_from_transaction_marks_paid(self):
        txn = PaymentTransaction.objects.create(
            user=self.user,
            reference="subscription:999",
            amount=self.subscription.monthly_amount,
            currency="BDT",
            status=PaymentTransactionStatus.SUCCESS,
        )
        period_start = self.subscription.last_paid_through
        period_end = period_start + timedelta(days=30)
        charge = SubscriptionCharge.objects.create(
            subscription=self.subscription,
            period_start=period_start,
            period_end=period_end,
            amount=self.subscription.monthly_amount,
            payment_transaction=txn,
        )
        self.subscription.status = DeviceSubscriptionStatus.GRACE
        self.subscription.grace_expires_at = timezone.now() - timedelta(days=1)
        self.subscription.save(update_fields=["status", "grace_expires_at"])

        services.sync_charge_from_transaction(txn)

        charge.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(charge.status, SubscriptionChargeStatus.PAID)
        self.assertEqual(self.subscription.status, DeviceSubscriptionStatus.ACTIVE)
        self.assertEqual(self.subscription.last_paid_through, charge.period_end)

    def test_refresh_subscription_status_suspends_when_grace_expires(self):
        period_start = self.subscription.last_paid_through
        period_end = period_start + timedelta(days=30)
        SubscriptionCharge.objects.create(
            subscription=self.subscription,
            period_start=period_start,
            period_end=period_end,
            amount=self.subscription.monthly_amount,
        )
        self.subscription.status = DeviceSubscriptionStatus.GRACE
        self.subscription.grace_expires_at = timezone.now() - timedelta(days=1)
        self.subscription.save(update_fields=["status", "grace_expires_at"])

        services.refresh_subscription_status(self.subscription, now=timezone.now())

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DeviceSubscriptionStatus.SUSPENDED)

    def test_customer_payload_fills_required_fields(self):
        self.user.full_name = ""
        self.user.phone_number = ""
        self.user.address = ""
        self.user.email = ""
        self.user.save(update_fields=["full_name", "phone_number", "address", "email"])
        self.subscription.originating_order = None
        self.subscription.save(update_fields=["originating_order"])
        payload = services._customer_payload(self.subscription)
        for key in [
            "customer_name",
            "customer_address",
            "customer_phone",
            "customer_city",
            "customer_post_code",
            "customer_email",
        ]:
            self.assertTrue(payload.get(key), f"{key} should not be blank")

    @patch("notifications.sms.SMSClient.send_text")
    def test_due_soon_reminder_sent_once(self, sms_mock):
        self.user.phone_number = "+8801000000000"
        self.user.save(update_fields=["phone_number"])
        base_now = timezone.now()
        due_at = base_now + timedelta(days=5, minutes=5)
        self.subscription.next_due_at = due_at
        self.subscription.save(update_fields=["next_due_at"])

        sms_mock.return_value = {"status": "success"}

        sent = services.send_due_soon_sms_reminders(as_of=base_now)

        self.assertEqual(sent, 1)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.due_reminder_for_due_at, due_at)
        self.assertIsNotNone(self.subscription.due_reminder_sent_at)

        again = services.send_due_soon_sms_reminders(as_of=base_now)
        self.assertEqual(again, 0)
        sms_mock.assert_called_once()

    def test_process_due_subscriptions_ignores_cancelled(self):
        self.subscription.status = DeviceSubscriptionStatus.CANCELLED
        self.subscription.next_due_at = timezone.now() - timedelta(days=1)
        self.subscription.save()

        charges = services.process_due_subscriptions()
        self.assertEqual(len(charges), 0)

    def test_activate_subscription(self):
        self.subscription.status = DeviceSubscriptionStatus.CANCELLED
        self.subscription.save()

        # Simulate admin activating the subscription
        self.subscription.status = DeviceSubscriptionStatus.ACTIVE
        self.subscription.grace_expires_at = None
        self.subscription.save()

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, DeviceSubscriptionStatus.ACTIVE)
        self.assertIsNone(self.subscription.grace_expires_at)
