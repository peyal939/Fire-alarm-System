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
from products.models import Package, Order
from subscriptions.models import (
    DeviceSubscription,
    SubscriptionCharge,
    Invoice,
    InvoiceLineItem,
)
from subscriptions.enums import (
    InvoiceStatus,
    SubscriptionChargeStatus,
    DeviceSubscriptionStatus,
)
from subscriptions import invoice_utils


class InvoiceModelTests(TestCase):
    """Tests for Invoice model."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
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
        )

    def test_invoice_number_generation(self):
        """Test invoice number is generated correctly."""
        number1 = Invoice.generate_invoice_number()
        year = timezone.now().year
        self.assertTrue(number1.startswith(f"INV-{year}-"))
        self.assertEqual(number1, f"INV-{year}-000001")

        # Create invoice and generate next number
        Invoice.objects.create(
            number=number1,
            user=self.user,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )
        number2 = Invoice.generate_invoice_number()
        self.assertEqual(number2, f"INV-{year}-000002")

    def test_invoice_creation(self):
        """Test invoice creation with line items."""
        invoice = Invoice.objects.create(
            number=Invoice.generate_invoice_number(),
            user=self.user,
            order=self.order,
            subtotal=Decimal("2200.00"),
            tax=Decimal("0.00"),
            total=Decimal("2200.00"),
            status=InvoiceStatus.PAID,
        )
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertEqual(invoice.total, Decimal("2200.00"))

    def test_line_item_auto_total(self):
        """Test line item total is auto-calculated."""
        invoice = Invoice.objects.create(
            number=Invoice.generate_invoice_number(),
            user=self.user,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )
        item = InvoiceLineItem(
            invoice=invoice,
            description="Test Item",
            quantity=5,
            unit_price=Decimal("20.00"),
        )
        item.save()
        self.assertEqual(item.total, Decimal("100.00"))


class InvoiceUtilsTests(TestCase):
    """Tests for invoice utility functions."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            full_name="Test User",
        )
        self.package = Package.objects.create(
            name="Fire Alarm Basic",
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
            order_status="paid",
            customer_name="Test Customer",
            customer_email="customer@example.com",
        )

    def test_create_invoice_for_order(self):
        """Test invoice creation from order."""
        invoice = invoice_utils.create_invoice_for_order(self.order)

        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.user, self.user)
        self.assertEqual(invoice.order, self.order)
        self.assertEqual(invoice.total, Decimal("2200.00"))
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

        # Check line items created
        self.assertTrue(invoice.line_items.exists())

    @patch("subscriptions.invoice_utils.generate_invoice_pdf")
    def test_save_invoice_pdf(self, mock_generate):
        """Test PDF generation and saving."""
        mock_generate.return_value = b"%PDF-1.4 test content"

        invoice = invoice_utils.create_invoice_for_order(self.order)
        filepath = invoice_utils.save_invoice_pdf(invoice)

        mock_generate.assert_called_once_with(invoice)
        self.assertTrue(filepath.endswith(".pdf"))
        invoice.refresh_from_db()
        self.assertTrue(invoice.pdf_file)


class InvoiceAPITests(APITestCase):
    """Tests for Invoice API endpoints."""

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
            quantity=2,
            amount=Decimal("2200.00"),
        )
        self.invoice = Invoice.objects.create(
            number="INV-2025-000001",
            user=self.user,
            order=self.order,
            subtotal=Decimal("2200.00"),
            tax=Decimal("0.00"),
            total=Decimal("2200.00"),
            status=InvoiceStatus.PAID,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description="Test Package - Device",
            quantity=2,
            unit_price=Decimal("1000.00"),
            total=Decimal("2000.00"),
        )

    def test_user_list_invoices(self):
        """Test user can list their invoices."""
        self.client.force_authenticate(user=self.user)
        url = reverse("user-invoices-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Handle both paginated and non-paginated responses
        data = response.data.get("results", response.data) if isinstance(response.data, dict) else response.data
        self.assertGreaterEqual(len(data), 1)
        # Check that our invoice is in the list
        invoice_numbers = [inv["number"] for inv in data]
        self.assertIn("INV-2025-000001", invoice_numbers)

    def test_user_retrieve_invoice(self):
        """Test user can retrieve invoice detail."""
        self.client.force_authenticate(user=self.user)
        url = reverse("user-invoices-detail", kwargs={"pk": self.invoice.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["number"], "INV-2025-000001")
        self.assertIn("line_items", response.data)

    def test_user_cannot_see_other_invoices(self):
        """Test user cannot see other user's invoices."""
        other_user = User.objects.create_user(
            email="other@example.com",
            password="otherpass123",
        )
        self.client.force_authenticate(user=other_user)

        url = reverse("user-invoices-detail", kwargs={"pk": self.invoice.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("subscriptions.invoice_views.invoice_utils.save_invoice_pdf")
    def test_download_pdf(self, mock_save):
        """Test PDF download endpoint."""
        from django.core.files.base import ContentFile
        # Setup - create a real file content
        pdf_content = b"%PDF-1.4 test content"
        self.invoice.pdf_file.save("test.pdf", ContentFile(pdf_content))
        self.invoice.save()

        self.client.force_authenticate(user=self.user)
        url = reverse("user-invoices-download-pdf", kwargs={"pk": self.invoice.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_admin_list_all_invoices(self):
        """Test admin can list all invoices."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-invoices-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_create_invoice_for_order(self):
        """Test admin can create invoice for order."""
        # Create new order without invoice
        new_order = Order.objects.create(
            user=self.user,
            package=self.package,
            quantity=1,
            amount=Decimal("1100.00"),
            order_status="paid",
        )

        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-invoices-create-for-order")
        response = self.client.post(url, {"order_id": new_order.pk}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Invoice.objects.filter(order=new_order).exists())

    def test_admin_create_duplicate_invoice_fails(self):
        """Test creating invoice for order that already has one fails."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-invoices-create-for-order")
        response = self.client.post(url, {"order_id": self.order.pk}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.data["detail"])

    def test_unauthenticated_access_denied(self):
        """Test unauthenticated requests are denied."""
        url = reverse("user-invoices-list")
        response = self.client.get(url)

        # DRF returns 403 Forbidden for unauthenticated requests by default
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
