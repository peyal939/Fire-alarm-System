from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from shurjopay.models import PaymentTransaction


class ShurjoPayViewSyncTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("sync@example.com", "Passw0rd!")
        self.client.force_authenticate(user=self.user)

    @patch("subscriptions.services.sync_charge_from_transaction")
    @patch("shurjopay.services.verify_payment")
    def test_verify_view_syncs_subscription_charge(self, verify_mock, sync_mock):
        txn = PaymentTransaction.objects.create(
            user=self.user,
            reference="subscription:1",
            amount=100,
            currency="BDT",
            sp_order_id="SP-123",
            status=PaymentTransaction.Status.INITIATED,
        )

        verify_mock.return_value = SimpleNamespace(transaction_status="success")

        response = self.client.post(
            reverse("shurjopay-verify"),
            {"order_id": "SP-123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.SUCCESS)
        sync_mock.assert_called_once_with(txn)

    @patch("subscriptions.services.sync_charge_from_transaction")
    def test_cancel_view_syncs_subscription_charge(self, sync_mock):
        txn = PaymentTransaction.objects.create(
            user=self.user,
            reference="subscription:2",
            amount=100,
            currency="BDT",
            sp_order_id="SP-456",
            status=PaymentTransaction.Status.INITIATED,
        )

        response = self.client.get(
            reverse("shurjopay-cancel"),
            {"order_id": "SP-456", "format": "json"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.CANCELLED)
        sync_mock.assert_called_once_with(txn)

    @patch("subscriptions.services.sync_charge_from_transaction")
    @patch("shurjopay.services.verify_payment")
    def test_return_view_json_response_and_sync(self, verify_mock, sync_mock):
        txn = PaymentTransaction.objects.create(
            user=self.user,
            reference="subscription:3",
            amount=150,
            currency="BDT",
            sp_order_id="SP-789",
            status=PaymentTransaction.Status.INITIATED,
        )

        verify_mock.return_value = SimpleNamespace(
            transaction_status="success", message="Payment successful"
        )

        response = self.client.get(
            reverse("shurjopay-return"),
            {"order_id": "SP-789", "format": "json"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "Payment successful")

        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.SUCCESS)
        sync_mock.assert_called_once_with(txn)
