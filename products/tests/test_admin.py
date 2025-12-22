"""Tests for admin views - order management, reports, and dashboard."""
from __future__ import annotations

from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from products.models import Package, Order
from products.enums import OrderStatus


class AdminOrderManagementTests(APITestCase):
    """Tests for admin order management endpoints."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            password="userpass123",
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
            quantity=2,
            amount=Decimal("2200.00"),
            order_status=OrderStatus.PAID,
        )

    def test_admin_list_orders(self):
        """Test admin can list all orders."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-orders-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertEqual(response.data["count"], 1)

    def test_admin_list_orders_with_filters(self):
        """Test admin can filter orders."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-orders-list")
        
        # Filter by status
        response = self.client.get(url, {"status": OrderStatus.PAID})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        # Filter by non-existent status
        response = self.client.get(url, {"status": OrderStatus.PENDING})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_admin_get_order_detail(self):
        """Test admin can get order details."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-order-detail", kwargs={"order_id": self.order.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.order.id)

    def test_admin_update_order_status(self):
        """Test admin can update order status."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-order-update", kwargs={"order_id": self.order.id})
        response = self.client.patch(url, {"order_status": OrderStatus.SHIPPED})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["order_status"], OrderStatus.SHIPPED)
        
        # Verify in database
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_status, OrderStatus.SHIPPED)

    def test_admin_update_invalid_status(self):
        """Test admin cannot set invalid status."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-order-update", kwargs={"order_id": self.order.id})
        response = self.client.patch(url, {"order_status": "invalid_status"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("allowed", response.data)

    def test_admin_bulk_update_orders(self):
        """Test admin can bulk update order status."""
        # Create additional orders
        order2 = Order.objects.create(
            user=self.user,
            package=self.package,
            quantity=1,
            amount=Decimal("1100.00"),
            order_status=OrderStatus.PAID,
        )

        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-orders-bulk-update")
        response = self.client.post(url, {
            "order_ids": [self.order.id, order2.id],
            "order_status": OrderStatus.PROCESSING,
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated_count"], 2)

        # Verify in database
        self.order.refresh_from_db()
        order2.refresh_from_db()
        self.assertEqual(self.order.order_status, OrderStatus.PROCESSING)
        self.assertEqual(order2.order_status, OrderStatus.PROCESSING)

    def test_non_admin_cannot_access(self):
        """Test regular user cannot access admin endpoints."""
        self.client.force_authenticate(user=self.user)
        url = reverse("admin-orders-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AdminReportTests(APITestCase):
    """Tests for admin report endpoints."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            password="userpass123",
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
            quantity=2,
            amount=Decimal("2200.00"),
            order_status=OrderStatus.PAID,
        )

    def test_order_report_json(self):
        """Test order report returns JSON."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-report-orders")
        today = timezone.now().date()
        response = self.client.get(url, {
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("summary", response.data)
        self.assertIn("total_orders", response.data["summary"])

    def test_order_report_csv(self):
        """Test order report returns CSV."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-report-orders")
        today = timezone.now().date()
        response = self.client.get(url, {
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
            "output_format": "csv",
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv")

    def test_order_report_requires_dates(self):
        """Test order report requires date parameters."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-report-orders")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_from", response.data["detail"])

    def test_payment_report(self):
        """Test payment report endpoint."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-report-payments")
        today = timezone.now().date()
        response = self.client.get(url, {
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("summary", response.data)
        self.assertIn("success_rate", response.data["summary"])

    def test_subscription_report(self):
        """Test subscription report endpoint."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-report-subscriptions")
        today = timezone.now().date()
        response = self.client.get(url, {
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("summary", response.data)
        self.assertIn("mrr", response.data["summary"])


class AdminDashboardTests(APITestCase):
    """Tests for admin dashboard endpoints."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            password="userpass123",
        )
        self.package = Package.objects.create(
            name="Test Package",
            min_quantity=1,
            max_quantity=10,
            price_per_device=Decimal("1000.00"),
            mrf=Decimal("100.00"),
        )
        Order.objects.create(
            user=self.user,
            package=self.package,
            quantity=2,
            amount=Decimal("2200.00"),
            order_status=OrderStatus.PAID,
        )

    def test_dashboard_overview(self):
        """Test dashboard overview endpoint."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-dashboard-overview")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("orders", response.data)
        self.assertIn("revenue", response.data)
        self.assertIn("subscriptions", response.data)
        self.assertIn("devices", response.data)
        self.assertIn("payments", response.data)

    def test_revenue_trend_daily(self):
        """Test daily revenue trend endpoint."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-dashboard-revenue-trend")
        response = self.client.get(url, {"period": "daily", "days": 7})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["period"], "daily")
        self.assertIn("data", response.data)

    def test_revenue_trend_monthly(self):
        """Test monthly revenue trend endpoint."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-dashboard-revenue-trend")
        response = self.client.get(url, {"period": "monthly", "months": 6})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["period"], "monthly")
        self.assertIn("data", response.data)

    def test_order_status_breakdown(self):
        """Test order status breakdown endpoint."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-dashboard-order-status")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("breakdown", response.data)
