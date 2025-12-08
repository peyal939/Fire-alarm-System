from __future__ import annotations

import logging

from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from common.permissions import IsSuperAdmin, IsSuperAdminOrCompanyAdmin
from .models import Invoice
from .invoice_serializers import (
    InvoiceSerializer,
    InvoiceListSerializer,
    InvoiceAdminSerializer,
)
from . import invoice_utils


logger = logging.getLogger(__name__)


@extend_schema(tags=["Invoices"])
class UserInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """User endpoints for viewing their invoices."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "list":
            return InvoiceListSerializer
        return InvoiceSerializer

    def get_queryset(self):
        return (
            Invoice.objects.filter(user=self.request.user)
            .select_related("user", "order", "subscription_charge")
            .prefetch_related("line_items")
            .order_by("-issued_at")
        )

    @extend_schema(
        summary="Download invoice PDF",
        responses={200: {"type": "string", "format": "binary"}},
    )
    @action(detail=True, methods=["get"], url_path="pdf")
    def download_pdf(self, request, pk=None):
        """Download the invoice as a PDF."""
        invoice = self.get_object()

        # Generate PDF if not already generated
        if not invoice.pdf_file:
            try:
                invoice_utils.save_invoice_pdf(invoice)
            except Exception as e:
                logger.exception("Failed to generate PDF for invoice %s", invoice.number)
                return Response(
                    {"detail": "Failed to generate PDF."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Serve the PDF
        try:
            pdf_content = invoice.pdf_file.read()
            response = HttpResponse(pdf_content, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="invoice_{invoice.number}.pdf"'
            return response
        except Exception as e:
            logger.exception("Failed to read PDF for invoice %s", invoice.number)
            return Response(
                {"detail": "Failed to retrieve PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary="Regenerate invoice PDF",
        responses={200: InvoiceSerializer},
    )
    @action(detail=True, methods=["post"], url_path="regenerate-pdf")
    def regenerate_pdf(self, request, pk=None):
        """Regenerate the invoice PDF."""
        invoice = self.get_object()

        try:
            invoice_utils.save_invoice_pdf(invoice)
            return Response(InvoiceSerializer(invoice).data)
        except Exception as e:
            logger.exception("Failed to regenerate PDF for invoice %s", invoice.number)
            return Response(
                {"detail": "Failed to regenerate PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary="Get or create invoice for user's order",
        description="Returns the invoice for a paid order. Creates one automatically if it doesn't exist.",
        responses={
            200: InvoiceSerializer,
            400: {"description": "Order not paid or invalid"},
            404: {"description": "Order not found"},
        },
    )
    @action(detail=False, methods=["get"], url_path="order/(?P<order_id>[^/.]+)")
    def get_for_order(self, request, order_id=None):
        """
        Get invoice for a specific order. Auto-creates if order is paid and no invoice exists.
        This enables users to download invoices like professional e-commerce apps.
        """
        from products.models import Order
        from products.enums import OrderStatus

        # Get the order - must belong to current user
        try:
            order = Order.objects.get(
                pk=order_id,
                user=request.user,
                deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if order is paid
        if order.order_status not in [OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            return Response(
                {"detail": "Invoice is only available for paid orders."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if invoice already exists
        invoice = Invoice.objects.filter(order=order).first()

        if not invoice:
            # Auto-create invoice for paid order
            try:
                invoice = invoice_utils.create_invoice_for_order(order)
                logger.info("Auto-created invoice %s for order %s", invoice.number, order.id)
            except Exception as e:
                logger.exception("Failed to create invoice for order %s", order.id)
                return Response(
                    {"detail": "Failed to create invoice."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Auto-generate PDF if not exists
        if not invoice.pdf_file:
            try:
                invoice_utils.save_invoice_pdf(invoice)
            except Exception as e:
                logger.warning("Failed to auto-generate PDF for invoice %s: %s", invoice.number, e)

        return Response(InvoiceSerializer(invoice).data)

    @extend_schema(
        summary="Download invoice PDF for order",
        description="Downloads the PDF invoice for a specific order. Auto-creates invoice if needed.",
        responses={
            200: {"type": "string", "format": "binary"},
            400: {"description": "Order not paid"},
            404: {"description": "Order not found"},
        },
    )
    @action(detail=False, methods=["get"], url_path="order/(?P<order_id>[^/.]+)/pdf")
    def download_for_order(self, request, order_id=None):
        """
        Download invoice PDF for a specific order.
        Auto-creates invoice and PDF if they don't exist.
        """
        from products.models import Order
        from products.enums import OrderStatus

        # Get the order - must belong to current user
        try:
            order = Order.objects.get(
                pk=order_id,
                user=request.user,
                deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if order is paid
        if order.order_status not in [OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            return Response(
                {"detail": "Invoice is only available for paid orders."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create invoice
        invoice = Invoice.objects.filter(order=order).first()

        if not invoice:
            try:
                invoice = invoice_utils.create_invoice_for_order(order)
                logger.info("Auto-created invoice %s for order %s", invoice.number, order.id)
            except Exception as e:
                logger.exception("Failed to create invoice for order %s", order.id)
                return Response(
                    {"detail": "Failed to create invoice."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Generate PDF if not exists
        if not invoice.pdf_file:
            try:
                invoice_utils.save_invoice_pdf(invoice)
            except Exception as e:
                logger.exception("Failed to generate PDF for invoice %s", invoice.number)
                return Response(
                    {"detail": "Failed to generate PDF."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Serve the PDF
        try:
            pdf_content = invoice.pdf_file.read()
            response = HttpResponse(pdf_content, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="invoice_{invoice.number}.pdf"'
            return response
        except Exception as e:
            logger.exception("Failed to read PDF for invoice %s", invoice.number)
            return Response(
                {"detail": "Failed to retrieve PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@extend_schema(tags=["Invoices (Admin)"])
class AdminInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin endpoints for managing all invoices."""

    serializer_class = InvoiceAdminSerializer
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get_queryset(self):
        qs = (
            Invoice.objects.select_related("user", "order", "subscription_charge")
            .prefetch_related("line_items")
            .order_by("-issued_at")
        )

        user = self.request.user
        role = getattr(user, "role", "")

        # Filter by role
        if not (user.is_superuser or role == "superadmin"):
            if role == "company_admin":
                # Company admin sees their own invoices
                qs = qs.filter(user=user)
            else:
                qs = qs.none()

        # Apply filters
        status_filter = self.request.query_params.get("status")
        user_id = self.request.query_params.get("user_id")
        order_id = self.request.query_params.get("order_id")

        if status_filter:
            qs = qs.filter(status=status_filter)
        if user_id:
            try:
                qs = qs.filter(user_id=int(user_id))
            except (TypeError, ValueError):
                pass
        if order_id:
            try:
                qs = qs.filter(order_id=int(order_id))
            except (TypeError, ValueError):
                pass

        return qs

    @extend_schema(
        summary="Download invoice PDF (admin)",
        responses={200: {"type": "string", "format": "binary"}},
    )
    @action(detail=True, methods=["get"], url_path="pdf")
    def download_pdf(self, request, pk=None):
        """Download the invoice as a PDF."""
        invoice = self.get_object()

        if not invoice.pdf_file:
            try:
                invoice_utils.save_invoice_pdf(invoice)
            except Exception as e:
                logger.exception("Failed to generate PDF for invoice %s", invoice.number)
                return Response(
                    {"detail": "Failed to generate PDF."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        try:
            pdf_content = invoice.pdf_file.read()
            response = HttpResponse(pdf_content, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="invoice_{invoice.number}.pdf"'
            return response
        except Exception as e:
            logger.exception("Failed to read PDF for invoice %s", invoice.number)
            return Response(
                {"detail": "Failed to retrieve PDF."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary="Generate invoice for order (admin)",
        request={
            "application/json": {
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"],
            }
        },
        responses={201: InvoiceAdminSerializer},
    )
    @action(detail=False, methods=["post"], url_path="create-for-order")
    def create_for_order(self, request):
        """Create an invoice for a specific order."""
        from products.models import Order

        order_id = request.data.get("order_id")
        if not order_id:
            return Response(
                {"detail": "order_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            order = Order.objects.get(pk=order_id, deleted_at__isnull=True)
        except Order.DoesNotExist:
            return Response(
                {"detail": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if invoice already exists
        existing = Invoice.objects.filter(order=order).first()
        if existing:
            return Response(
                {
                    "detail": "Invoice already exists for this order.",
                    "invoice": InvoiceAdminSerializer(existing).data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            invoice = invoice_utils.create_invoice_for_order(order)
            return Response(
                InvoiceAdminSerializer(invoice).data,
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            logger.exception("Failed to create invoice for order %s", order_id)
            return Response(
                {"detail": f"Failed to create invoice: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
