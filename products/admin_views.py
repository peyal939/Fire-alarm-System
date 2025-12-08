"""
Admin views for order management, reports, and dashboard analytics.
"""
from __future__ import annotations

import csv
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
from io import StringIO

from django.db import models
from django.db.models import Sum, Count, Avg, F, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer, OpenApiResponse

from common.permissions import IsSuperAdmin, IsSuperAdminOrCompanyAdmin
from .enums import OrderStatus, PaymentMethod
from .models import Order, Package
from .serializers import OrderSerializer, OrderFulfillmentSerializer
from devices.services import order_has_capacity
from .models import OrderFulfillment

logger = logging.getLogger(__name__)


# =============================================================================
# Admin Order Management
# =============================================================================

@extend_schema(
    tags=["Admin - Orders"],
    summary="Admin: List all orders with filtering and pagination",
    parameters=[
        OpenApiParameter(name="status", type=str, description="Filter by order status"),
        OpenApiParameter(name="user_id", type=int, description="Filter by user ID"),
        OpenApiParameter(name="package_id", type=int, description="Filter by package ID"),
        OpenApiParameter(name="date_from", type=str, description="Filter from date (YYYY-MM-DD)"),
        OpenApiParameter(name="date_to", type=str, description="Filter to date (YYYY-MM-DD)"),
        OpenApiParameter(name="page", type=int, description="Page number"),
        OpenApiParameter(name="page_size", type=int, description="Items per page (default 20, max 100)"),
    ],
    responses={
        200: inline_serializer(
            name="AdminOrderListResponse",
            fields={
                "count": drf_serializers.IntegerField(),
                "page": drf_serializers.IntegerField(),
                "page_size": drf_serializers.IntegerField(),
                "total_pages": drf_serializers.IntegerField(),
                "results": OrderSerializer(many=True),
            },
        )
    },
)
class AdminOrderListView(APIView):
    """Admin endpoint for listing orders with advanced filtering."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    @extend_schema(operation_id="admin_orders_list")
    def get(self, request):
        qs = (
            Order.objects.select_related("user", "package")
            .filter(deleted_at__isnull=True)
            .order_by("-ordered_at")
        )

        # Status filter
        status_param = request.query_params.get("status")
        if status_param and status_param in {s for s, _ in OrderStatus.choices}:
            qs = qs.filter(order_status=status_param)

        # User filter
        user_id = request.query_params.get("user_id")
        if user_id:
            try:
                qs = qs.filter(user_id=int(user_id))
            except (TypeError, ValueError):
                pass

        # Package filter
        package_id = request.query_params.get("package_id")
        if package_id:
            try:
                qs = qs.filter(package_id=int(package_id))
            except (TypeError, ValueError):
                pass

        # Date range filter
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            try:
                qs = qs.filter(ordered_at__date__gte=date_from)
            except Exception:
                pass
        if date_to:
            try:
                qs = qs.filter(ordered_at__date__lte=date_to)
            except Exception:
                pass

        # Pagination
        page = int(request.query_params.get("page", 1))
        page_size = min(int(request.query_params.get("page_size", 20)), 100)
        start = (page - 1) * page_size
        end = start + page_size

        total_count = qs.count()
        orders = qs[start:end]

        return Response({
            "count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size,
            "results": OrderSerializer(orders, many=True).data,
        })


class AdminOrderDetailView(APIView):
    """Admin endpoint for viewing order details."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    @extend_schema(
        tags=["Admin - Orders"],
        summary="Admin: Get order details",
        operation_id="admin_order_detail",
        responses={200: OrderSerializer},
    )
    def get(self, request, order_id: int):
        try:
            order = Order.objects.select_related("user", "package").get(
                id=order_id,
                deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return Response({"detail": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(OrderSerializer(order).data)


@extend_schema(
    tags=["Admin - Orders"],
    summary="Admin: Update order status",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "order_status": {"type": "string", "enum": [s for s, _ in OrderStatus.choices]},
                "notes": {"type": "string", "description": "Optional notes for status change"},
            },
            "required": ["order_status"],
        }
    },
    responses={200: OrderSerializer},
)
class AdminOrderUpdateView(APIView):
    """Admin endpoint for updating order status."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def patch(self, request, order_id: int):
        try:
            order = Order.objects.select_related("user", "package").get(
                id=order_id,
                deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return Response({"detail": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("order_status")
        valid_statuses = {s for s, _ in OrderStatus.choices}
        
        if not new_status or new_status not in valid_statuses:
            return Response({
                "detail": "Invalid order_status",
                "allowed": sorted(list(valid_statuses)),
            }, status=status.HTTP_400_BAD_REQUEST)

        old_status = order.order_status
        if order.order_status != new_status:
            order.order_status = new_status
            order.updated_by = request.user
            order.save(update_fields=["order_status", "updated_by"])
            
            logger.info(
                "Order %s status changed from %s to %s by user %s",
                order.id, old_status, new_status, request.user.id
            )

        return Response(OrderSerializer(order).data)


@extend_schema(
    tags=["Admin - Orders"],
    summary="Admin: Bulk update order status",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "order_ids": {"type": "array", "items": {"type": "integer"}},
                "order_status": {"type": "string", "enum": [s for s, _ in OrderStatus.choices]},
            },
            "required": ["order_ids", "order_status"],
        }
    },
    responses={
        200: inline_serializer(
            name="BulkUpdateResponse",
            fields={
                "updated_count": drf_serializers.IntegerField(),
                "order_status": drf_serializers.CharField(),
            },
        )
    },
)
class AdminOrderBulkUpdateView(APIView):
    """Admin endpoint for bulk updating order status."""
    
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request):
        order_ids = request.data.get("order_ids", [])
        new_status = request.data.get("order_status")

        if not order_ids or not isinstance(order_ids, list):
            return Response(
                {"detail": "order_ids must be a non-empty array"},
                status=status.HTTP_400_BAD_REQUEST
            )

        valid_statuses = {s for s, _ in OrderStatus.choices}
        if not new_status or new_status not in valid_statuses:
            return Response({
                "detail": "Invalid order_status",
                "allowed": sorted(list(valid_statuses)),
            }, status=status.HTTP_400_BAD_REQUEST)

        updated_count = Order.objects.filter(
            id__in=order_ids,
            deleted_at__isnull=True,
        ).update(
            order_status=new_status,
            updated_by=request.user,
        )

        return Response({
            "updated_count": updated_count,
            "order_status": new_status,
        })


# =============================================================================
# Reports
# =============================================================================

@extend_schema(
    tags=["Admin - Reports"],
    summary="Admin: Generate order report",
    parameters=[
        OpenApiParameter(name="date_from", type=str, required=True, description="Start date (YYYY-MM-DD)"),
        OpenApiParameter(name="date_to", type=str, required=True, description="End date (YYYY-MM-DD)"),
        OpenApiParameter(name="status", type=str, description="Filter by order status"),
        OpenApiParameter(name="output_format", type=str, description="Output format: json or csv (default: json)"),
    ],
    responses={
        200: inline_serializer(
            name="OrderReportResponse",
            fields={
                "period": drf_serializers.DictField(),
                "summary": drf_serializers.DictField(),
                "status_breakdown": drf_serializers.ListField(),
                "orders": OrderSerializer(many=True),
            },
        )
    },
)
class AdminOrderReportView(APIView):
    """Generate order reports with date filtering and CSV export."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        from datetime import datetime
        
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        output_format = request.query_params.get("output_format", "json")

        if not date_from or not date_to:
            return Response(
                {"detail": "date_from and date_to are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert to timezone-aware datetime range for proper filtering
        date_from_dt = timezone.make_aware(datetime.strptime(date_from, "%Y-%m-%d"))
        date_to_dt = timezone.make_aware(datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))

        qs = Order.objects.select_related("user", "package").filter(
            deleted_at__isnull=True,
            ordered_at__gte=date_from_dt,
            ordered_at__lte=date_to_dt,
        ).order_by("-ordered_at")

        # Status filter
        status_param = request.query_params.get("status")
        if status_param and status_param in {s for s, _ in OrderStatus.choices}:
            qs = qs.filter(order_status=status_param)

        # Summary stats
        summary = qs.aggregate(
            total_orders=Count("id"),
            total_revenue=Sum("amount"),
            avg_order_value=Avg("amount"),
        )

        # Status breakdown
        status_breakdown = list(
            qs.values("order_status")
            .annotate(count=Count("id"), revenue=Sum("amount"))
            .order_by("-count")
        )

        if output_format == "csv":
            return self._generate_csv(qs, date_from, date_to)

        return Response({
            "period": {"from": date_from, "to": date_to},
            "summary": {
                "total_orders": summary["total_orders"] or 0,
                "total_revenue": str(summary["total_revenue"] or Decimal("0.00")),
                "avg_order_value": str(summary["avg_order_value"] or Decimal("0.00")),
            },
            "status_breakdown": status_breakdown,
            "orders": OrderSerializer(qs[:500], many=True).data,  # Limit to 500 in JSON
        })

    def _generate_csv(self, queryset, date_from, date_to):
        output = StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "Order ID", "Date", "User Email", "Package", "Quantity",
            "Amount", "Status", "Shipping Address"
        ])

        dhaka = ZoneInfo("Asia/Dhaka")

        for order in queryset:
            order_dt = order.ordered_at
            try:
                order_dt = timezone.localtime(order_dt, dhaka) if order_dt else None
            except Exception:
                pass
            writer.writerow([
                order.id,
                order_dt.strftime("%Y-%m-%d %H:%M:%S") if order_dt else "",
                order.user.email if order.user else "",
                order.package.name if order.package else "",
                order.quantity,
                str(order.amount),
                order.order_status,
                order.shipping_address or "",
            ])

        output.seek(0)
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="orders_{date_from}_to_{date_to}.csv"'
        return response


@extend_schema(
    tags=["Admin - Reports"],
    summary="Admin: Generate payment report",
    parameters=[
        OpenApiParameter(name="date_from", type=str, required=True, description="Start date (YYYY-MM-DD)"),
        OpenApiParameter(name="date_to", type=str, required=True, description="End date (YYYY-MM-DD)"),
        OpenApiParameter(name="output_format", type=str, description="Output format: json or csv (default: json)"),
    ],
    responses={
        200: inline_serializer(
            name="PaymentReportResponse",
            fields={
                "period": drf_serializers.DictField(),
                "summary": drf_serializers.DictField(),
                "status_breakdown": drf_serializers.ListField(),
                "payment_method_breakdown": drf_serializers.ListField(),
                "records": drf_serializers.ListField(),
            },
        )
    },
)
class AdminPaymentReportView(APIView):
    """Generate payment/transaction reports."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        from shurjopay.models import PaymentTransaction
        from shurjopay.enums import PaymentTransactionStatus
        from datetime import datetime
        from products.models import Order

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        output_format = request.query_params.get("output_format", "json")

        if not date_from or not date_to:
            return Response(
                {"detail": "date_from and date_to are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert to timezone-aware datetime range for proper filtering
        date_from_dt = timezone.make_aware(datetime.strptime(date_from, "%Y-%m-%d"))
        date_to_dt = timezone.make_aware(datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))

        qs = PaymentTransaction.objects.filter(
            created_at__gte=date_from_dt,
            created_at__lte=date_to_dt,
        ).order_by("-created_at")

        cod_orders = Order.objects.select_related("user").filter(
            deleted_at__isnull=True,
            payment_method=PaymentMethod.CASH_ON_DELIVERY,
            order_status__in=[
                OrderStatus.PAID,
                OrderStatus.PROCESSING,
                OrderStatus.SHIPPED,
                OrderStatus.DELIVERED,
            ],
            ordered_at__gte=date_from_dt,
            ordered_at__lte=date_to_dt,
        ).order_by("-ordered_at")

        # Summary
        summary = qs.aggregate(
            total_transactions=Count("id"),
            total_amount=Sum("amount"),
        )

        cod_summary = cod_orders.aggregate(
            cod_orders=Count("id"),
            cod_amount=Sum("amount"),
        )

        # Status breakdown
        status_breakdown = list(
            qs.values("status")
            .annotate(count=Count("id"), amount=Sum("amount"))
            .order_by("-count")
        )

        payment_method_breakdown = [
            {
                "payment_method": "online",
                "count": summary["total_transactions"] or 0,
                "amount": str(summary["total_amount"] or Decimal("0.00")),
            },
            {
                "payment_method": "cod",
                "count": cod_summary["cod_orders"] or 0,
                "amount": str(cod_summary["cod_amount"] or Decimal("0.00")),
            },
        ]

        # Success rate
        total = summary["total_transactions"] or 0
        successful = qs.filter(status=PaymentTransactionStatus.SUCCESS).count()
        success_rate = (successful / total * 100) if total > 0 else 0

        combined_total_amount = (summary["total_amount"] or Decimal("0.00")) + (
            cod_summary["cod_amount"] or Decimal("0.00")
        )

        if output_format == "csv":
            return self._generate_csv(qs, cod_orders, date_from, date_to)

        return Response({
            "period": {"from": date_from, "to": date_to},
            "summary": {
                "total_transactions": total,
                "total_amount": str(combined_total_amount),
                "successful_transactions": successful,
                "success_rate": round(success_rate, 2),
                "cod_orders": cod_summary["cod_orders"] or 0,
                "cod_amount": str(cod_summary["cod_amount"] or Decimal("0.00")),
            },
            "status_breakdown": status_breakdown,
            "payment_method_breakdown": payment_method_breakdown,
            "records": self._build_records(qs, cod_orders),
        })

    def _extract_order_id(self, reference: str | None) -> int | None:
        if not reference:
            return None
        ref = str(reference)
        if ref.startswith("order:"):
            try:
                return int(ref.split(":", 1)[1])
            except (TypeError, ValueError):
                return None
        try:
            return int(ref)
        except (TypeError, ValueError):
            return None

    def _build_records(self, txn_queryset, cod_queryset):
        records = []
        for txn in txn_queryset.select_related("user"):
            records.append(
                {
                    "type": "transaction",
                    "payment_method": "online",
                    "id": txn.id,
                    "user_email": txn.user.email if txn.user else "",
                    "order_id": self._extract_order_id(txn.reference),
                    "reference": txn.reference,
                    "amount": str(txn.amount),
                    "currency": txn.currency,
                    "status": txn.status,
                    "sp_order_id": txn.sp_order_id,
                    "created_at": txn.created_at,
                }
            )

        for order in cod_queryset:
            records.append(
                {
                    "type": "order",
                    "payment_method": "cod",
                    "id": order.id,
                    "user_email": order.user.email if order.user else "",
                    "order_id": order.id,
                    "reference": order.reference,
                    "amount": str(order.amount),
                    "currency": order.currency,
                    "status": order.order_status,
                    "sp_order_id": "",
                    "created_at": order.ordered_at,
                }
            )
        return records

    def _generate_csv(self, txn_queryset, cod_queryset, date_from, date_to):
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "Type",
            "Payment Method",
            "ID",
            "Order ID",
            "Date",
            "User Email",
            "Reference",
            "Amount",
            "Currency",
            "Status",
            "SP Order ID",
        ])

        dhaka = ZoneInfo("Asia/Dhaka")

        for txn in txn_queryset.select_related("user"):
            created_dt = txn.created_at
            try:
                created_dt = timezone.localtime(created_dt, dhaka) if created_dt else None
            except Exception:
                pass
            writer.writerow([
                "transaction",
                "online",
                txn.id,
                self._extract_order_id(txn.reference) or "",
                created_dt.strftime("%Y-%m-%d %H:%M:%S") if created_dt else "",
                txn.user.email if txn.user else "",
                txn.reference,
                str(txn.amount),
                txn.currency,
                txn.status,
                txn.sp_order_id,
            ])

        for order in cod_queryset:
            order_dt = order.ordered_at
            try:
                order_dt = timezone.localtime(order_dt, dhaka) if order_dt else None
            except Exception:
                pass
            writer.writerow([
                "order",
                "cod",
                order.id,
                order.id,
                order_dt.strftime("%Y-%m-%d %H:%M:%S") if order_dt else "",
                order.user.email if order.user else "",
                order.reference,
                str(order.amount),
                order.currency,
                order.order_status,
                "",
            ])

        output.seek(0)
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="payments_{date_from}_to_{date_to}.csv"'
        return response


@extend_schema(
    tags=["Admin - Fulfillments"],
    summary="Admin: List order fulfillments",
    parameters=[
        OpenApiParameter(name="order_id", type=int, description="Filter by order id"),
        OpenApiParameter(name="search", type=str, description="Search by hardware identifier"),
        OpenApiParameter(name="page", type=int, description="Page number"),
        OpenApiParameter(name="page_size", type=int, description="Items per page (default 20, max 100)"),
    ],
    responses={
        200: inline_serializer(
            name="FulfillmentListResponse",
            fields={
                "count": drf_serializers.IntegerField(),
                "page": drf_serializers.IntegerField(),
                "page_size": drf_serializers.IntegerField(),
                "total_pages": drf_serializers.IntegerField(),
                "results": OrderFulfillmentSerializer(many=True),
            },
        )
    },
)
class AdminFulfillmentListView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        qs = OrderFulfillment.objects.select_related("order", "order__user").filter(deleted_at__isnull=True)

        order_id = request.query_params.get("order_id")
        if order_id:
            try:
                qs = qs.filter(order_id=int(order_id))
            except (TypeError, ValueError):
                pass

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(hardware_identifier__icontains=search)

        page = int(request.query_params.get("page", 1))
        page_size = min(int(request.query_params.get("page_size", 20)), 100)
        start = (page - 1) * page_size
        end = start + page_size

        total_count = qs.count()
        fulfillments = qs.order_by("-created_at")[start:end]

        return Response(
            {
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size,
                "results": OrderFulfillmentSerializer(fulfillments, many=True).data,
            }
        )


@extend_schema(
    tags=["Admin - Fulfillments"],
    summary="Admin: Update or delete a fulfillment",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "new_order_id": {
                    "type": "integer",
                    "description": "Move this fulfillment to another order",
                },
            },
        }
    },
    responses={
        200: OrderFulfillmentSerializer,
        204: OpenApiResponse(description="Fulfillment deleted"),
        404: OpenApiResponse(description="Not found"),
    },
)
class AdminFulfillmentDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def _load_fulfillment(self, pk: int) -> OrderFulfillment | None:
        try:
            return OrderFulfillment.objects.select_related("order", "order__user").get(
                pk=pk, deleted_at__isnull=True
            )
        except OrderFulfillment.DoesNotExist:
            return None

    def delete(self, request, fulfillment_id: int):
        fulfillment = self._load_fulfillment(fulfillment_id)
        if not fulfillment:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            order = fulfillment.order
            fulfillment.deleted_at = timezone.now()
            fulfillment.deleted_by = request.user
            fulfillment.save(update_fields=["deleted_at", "deleted_by", "updated_at"])

            if order and order.assigned_devices:
                order.assigned_devices = max(0, (order.assigned_devices or 0) - 1)
                order.updated_by = request.user
                order.save(update_fields=["assigned_devices", "updated_by"])

        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, fulfillment_id: int):
        fulfillment = self._load_fulfillment(fulfillment_id)
        if not fulfillment:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        new_order_id = request.data.get("new_order_id") if isinstance(request.data, dict) else None
        if not new_order_id:
            return Response({"detail": "new_order_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_order = Order.objects.select_for_update().get(
                pk=int(new_order_id), deleted_at__isnull=True
            )
        except (Order.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Target order not found"}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            fulfillment = OrderFulfillment.objects.select_for_update().get(pk=fulfillment.pk)
            source_order = fulfillment.order

            if target_order.order_status != OrderStatus.PAID:
                return Response({"detail": "Target order must be paid"}, status=status.HTTP_400_BAD_REQUEST)

            ok, counts, message = order_has_capacity(target_order, role=fulfillment.device_role)
            if not ok:
                return Response({"detail": message or "Target order has no capacity"}, status=status.HTTP_400_BAD_REQUEST)

            fulfillment.order = target_order
            fulfillment.updated_by = request.user
            fulfillment.save(update_fields=["order", "updated_by", "updated_at"])

            # decrement source, increment target assigned counts
            if source_order:
                source_order.assigned_devices = max(0, (source_order.assigned_devices or 0) - 1)
                source_order.updated_by = request.user
                source_order.save(update_fields=["assigned_devices", "updated_by"])

            target_order.assigned_devices = counts["total"] + 1
            target_order.updated_by = request.user
            target_order.save(update_fields=["assigned_devices", "updated_by"])

        return Response(OrderFulfillmentSerializer(fulfillment).data)


@extend_schema(
    tags=["Admin - Reports"],
    summary="Admin: Generate subscription report",
    parameters=[
        OpenApiParameter(name="date_from", type=str, required=True, description="Start date (YYYY-MM-DD)"),
        OpenApiParameter(name="date_to", type=str, required=True, description="End date (YYYY-MM-DD)"),
        OpenApiParameter(name="output_format", type=str, description="Output format: json or csv (default: json)"),
    ],
    responses={
        200: inline_serializer(
            name="SubscriptionReportResponse",
            fields={
                "period": drf_serializers.DictField(),
                "summary": drf_serializers.DictField(),
                "status_breakdown": drf_serializers.ListField(),
                "subscriptions": drf_serializers.ListField(),
            },
        )
    },
)
class AdminSubscriptionReportView(APIView):
    """Generate subscription reports."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        from subscriptions.models import DeviceSubscription, SubscriptionCharge
        from subscriptions.enums import DeviceSubscriptionStatus, SubscriptionChargeStatus
        from datetime import datetime

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        output_format = request.query_params.get("output_format", "json")

        if not date_from or not date_to:
            return Response(
                {"detail": "date_from and date_to are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert to timezone-aware datetime range for proper filtering
        date_from_dt = timezone.make_aware(datetime.strptime(date_from, "%Y-%m-%d"))
        date_to_dt = timezone.make_aware(datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))

        # Active subscriptions
        active_subs = DeviceSubscription.objects.filter(
            status=DeviceSubscriptionStatus.ACTIVE
        ).count()

        # Subscriptions created in period
        new_subs = DeviceSubscription.objects.filter(
            created_at__gte=date_from_dt,
            created_at__lte=date_to_dt,
        ).count()

        # Charges in period
        charges = SubscriptionCharge.objects.filter(
            created_at__gte=date_from_dt,
            created_at__lte=date_to_dt,
        )

        charges_summary = charges.aggregate(
            total_charges=Count("id"),
            total_revenue=Sum("amount", filter=Q(status=SubscriptionChargeStatus.PAID)),
            paid_count=Count("id", filter=Q(status=SubscriptionChargeStatus.PAID)),
            failed_count=Count("id", filter=Q(status=SubscriptionChargeStatus.FAILED)),
        )

        # Status breakdown of all subscriptions
        status_breakdown = list(
            DeviceSubscription.objects.values("status")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # MRR calculation (Monthly Recurring Revenue)
        mrr = DeviceSubscription.objects.filter(
            status=DeviceSubscriptionStatus.ACTIVE
        ).aggregate(mrr=Sum("monthly_amount"))["mrr"] or Decimal("0.00")

        if output_format == "csv":
            return self._generate_csv(charges, date_from, date_to)

        # Get subscriptions list for table display
        subscriptions_qs = DeviceSubscription.objects.select_related(
            'device', 'device__user', 'originating_order', 'originating_order__package'
        ).order_by('-created_at')[:100]
        
        subscriptions_list = []
        for sub in subscriptions_qs:
            subscriptions_list.append({
                'id': sub.id,
                'device_name': sub.device.hardware_identifier if sub.device else 'N/A',
                'user_email': sub.device.user.email if sub.device and sub.device.user else 'N/A',
                'package_name': sub.originating_order.package.name if sub.originating_order and sub.originating_order.package else 'N/A',
                'monthly_amount': str(sub.monthly_amount),
                'status': sub.status,
                'created_at': sub.created_at.isoformat() if sub.created_at else None,
                'next_due_at': sub.next_due_at.isoformat() if sub.next_due_at else None,
            })

        return Response({
            "period": {"from": date_from, "to": date_to},
            "summary": {
                "active_subscriptions": active_subs,
                "new_subscriptions_in_period": new_subs,
                "mrr": str(mrr),
                "total_charges": charges_summary["total_charges"] or 0,
                "subscription_revenue": str(charges_summary["total_revenue"] or Decimal("0.00")),
                "paid_charges": charges_summary["paid_count"] or 0,
                "failed_charges": charges_summary["failed_count"] or 0,
            },
            "status_breakdown": status_breakdown,
            "subscriptions": subscriptions_list,
        })

    def _generate_csv(self, queryset, date_from, date_to):
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "Charge ID", "Date", "Subscription ID", "Device", "Period Start",
            "Period End", "Amount", "Status", "Failure Reason"
        ])

        for charge in queryset.select_related("subscription", "subscription__device"):
            writer.writerow([
                charge.id,
                charge.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                charge.subscription_id,
                charge.subscription.device.hardware_identifier if charge.subscription.device else "",
                charge.period_start.strftime("%Y-%m-%d") if charge.period_start else "",
                charge.period_end.strftime("%Y-%m-%d") if charge.period_end else "",
                str(charge.amount),
                charge.status,
                charge.failure_reason or "",
            ])

        output.seek(0)
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="subscriptions_{date_from}_to_{date_to}.csv"'
        return response


# =============================================================================
# Dashboard Analytics
# =============================================================================

@extend_schema(
    tags=["Admin - Dashboard"],
    summary="Admin: Dashboard overview statistics",
    responses={
        200: inline_serializer(
            name="DashboardOverviewResponse",
            fields={
                "orders": drf_serializers.DictField(),
                "revenue": drf_serializers.DictField(),
                "subscriptions": drf_serializers.DictField(),
                "devices": drf_serializers.DictField(),
                "payments": drf_serializers.DictField(),
            },
        )
    },
)
class AdminDashboardOverviewView(APIView):
    """Get dashboard overview statistics."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        from subscriptions.models import DeviceSubscription, SubscriptionCharge
        from subscriptions.enums import DeviceSubscriptionStatus, SubscriptionChargeStatus
        from shurjopay.models import PaymentTransaction
        from shurjopay.enums import PaymentTransactionStatus
        from devices.models import Device
        import datetime

        # Use timezone-aware datetime ranges for proper filtering
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + datetime.timedelta(days=1)
        
        this_month_start = today_start.replace(day=1)
        last_month_end = this_month_start - datetime.timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Order stats
        total_orders = Order.objects.filter(deleted_at__isnull=True).count()
        orders_today = Order.objects.filter(
            deleted_at__isnull=True,
            ordered_at__gte=today_start,
            ordered_at__lt=today_end,
        ).count()
        orders_this_month = Order.objects.filter(
            deleted_at__isnull=True,
            ordered_at__gte=this_month_start,
        ).count()
        pending_orders = Order.objects.filter(
            deleted_at__isnull=True,
            order_status__in=[OrderStatus.PENDING, OrderStatus.PROCESSING],
        ).count()

        # Revenue = orders where payment was received (PAID, DELIVERED, SHIPPED, PROCESSING)
        # These statuses all imply the customer has paid
        revenue_statuses = [OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED, OrderStatus.PROCESSING]
        
        # Revenue stats - today
        paid_today = Order.objects.filter(
            deleted_at__isnull=True,
            order_status__in=revenue_statuses,
            ordered_at__gte=today_start,
            ordered_at__lt=today_end,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        
        refunded_today = Order.objects.filter(
            deleted_at__isnull=True,
            order_status=OrderStatus.REFUNDED,
            ordered_at__gte=today_start,
            ordered_at__lt=today_end,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        
        revenue_today = paid_today - refunded_today
        
        # Revenue stats - this month
        paid_this_month = Order.objects.filter(
            deleted_at__isnull=True,
            order_status__in=revenue_statuses,
            ordered_at__gte=this_month_start,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        
        refunded_this_month = Order.objects.filter(
            deleted_at__isnull=True,
            order_status=OrderStatus.REFUNDED,
            ordered_at__gte=this_month_start,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        
        revenue_this_month = paid_this_month - refunded_this_month

        # Revenue stats - last month
        paid_last_month = Order.objects.filter(
            deleted_at__isnull=True,
            order_status__in=revenue_statuses,
            ordered_at__gte=last_month_start,
            ordered_at__lt=this_month_start,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        
        refunded_last_month = Order.objects.filter(
            deleted_at__isnull=True,
            order_status=OrderStatus.REFUNDED,
            ordered_at__gte=last_month_start,
            ordered_at__lt=this_month_start,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        
        revenue_last_month = paid_last_month - refunded_last_month

        # Subscription stats
        active_subscriptions = DeviceSubscription.objects.filter(
            status=DeviceSubscriptionStatus.ACTIVE
        ).count()
        
        mrr = DeviceSubscription.objects.filter(
            status=DeviceSubscriptionStatus.ACTIVE
        ).aggregate(mrr=Sum("monthly_amount"))["mrr"] or Decimal("0.00")

        subscription_revenue_this_month = SubscriptionCharge.objects.filter(
            status=SubscriptionChargeStatus.PAID,
            created_at__gte=this_month_start,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        # Device stats
        total_devices = Device.objects.filter(deleted_at__isnull=True).count()
        devices_this_month = Device.objects.filter(
            deleted_at__isnull=True,
            registered_at__gte=this_month_start,
        ).count()

        # Payment success rate this month
        payments_this_month = PaymentTransaction.objects.filter(
            created_at__gte=this_month_start,
        )
        total_payments = payments_this_month.count()
        successful_payments = payments_this_month.filter(
            status=PaymentTransactionStatus.SUCCESS
        ).count()
        payment_success_rate = (successful_payments / total_payments * 100) if total_payments > 0 else 0

        return Response({
            "orders": {
                "total": total_orders,
                "today": orders_today,
                "this_month": orders_this_month,
                "pending": pending_orders,
            },
            "revenue": {
                "today": str(revenue_today),
                "this_month": str(revenue_this_month),
                "last_month": str(revenue_last_month),
                "growth_percent": self._calc_growth(revenue_last_month, revenue_this_month),
            },
            "subscriptions": {
                "active": active_subscriptions,
                "mrr": str(mrr),
                "revenue_this_month": str(subscription_revenue_this_month),
            },
            "devices": {
                "total": total_devices,
                "registered_this_month": devices_this_month,
            },
            "payments": {
                "this_month": total_payments,
                "successful": successful_payments,
                "success_rate": round(payment_success_rate, 2),
            },
        })

    def _calc_growth(self, old_value, new_value):
        if not old_value or old_value == 0:
            return 0 if not new_value else 100
        growth = ((new_value - old_value) / old_value) * 100
        return round(float(growth), 2)


@extend_schema(
    tags=["Admin - Dashboard"],
    summary="Admin: Revenue trend over time",
    parameters=[
        OpenApiParameter(name="period", type=str, description="Period: daily or monthly (default: daily)"),
        OpenApiParameter(name="days", type=int, description="Number of days for daily (default: 30)"),
        OpenApiParameter(name="months", type=int, description="Number of months for monthly (default: 12)"),
    ],
    responses={
        200: inline_serializer(
            name="RevenueTrendResponse",
            fields={
                "period": drf_serializers.CharField(),
                "days": drf_serializers.IntegerField(required=False),
                "months": drf_serializers.IntegerField(required=False),
                "data": drf_serializers.ListField(),
            },
        )
    },
)
class AdminRevenueTrendView(APIView):
    """Get revenue trend data for charts."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        period = request.query_params.get("period", "daily")
        
        if period == "monthly":
            months = int(request.query_params.get("months", 12))
            return self._get_monthly_trend(months)
        else:
            days = int(request.query_params.get("days", 30))
            return self._get_daily_trend(days)

    def _get_daily_trend(self, days):
        from subscriptions.models import SubscriptionCharge
        from subscriptions.enums import SubscriptionChargeStatus

        start_date = timezone.now().date() - timedelta(days=days)

        # Order revenue by day
        order_revenue = (
            Order.objects.filter(
                deleted_at__isnull=True,
                order_status=OrderStatus.PAID,
                ordered_at__date__gte=start_date,
            )
            .annotate(date=TruncDate("ordered_at"))
            .values("date")
            .annotate(revenue=Sum("amount"), count=Count("id"))
            .order_by("date")
        )

        # Subscription revenue by day
        sub_revenue = (
            SubscriptionCharge.objects.filter(
                status=SubscriptionChargeStatus.PAID,
                created_at__date__gte=start_date,
            )
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(revenue=Sum("amount"), count=Count("id"))
            .order_by("date")
        )

        # Merge data
        data = {}
        for item in order_revenue:
            date_str = item["date"].strftime("%Y-%m-%d")
            data[date_str] = {
                "date": date_str,
                "order_revenue": str(item["revenue"] or 0),
                "order_count": item["count"],
                "subscription_revenue": "0.00",
                "subscription_count": 0,
            }

        for item in sub_revenue:
            date_str = item["date"].strftime("%Y-%m-%d")
            if date_str in data:
                data[date_str]["subscription_revenue"] = str(item["revenue"] or 0)
                data[date_str]["subscription_count"] = item["count"]
            else:
                data[date_str] = {
                    "date": date_str,
                    "order_revenue": "0.00",
                    "order_count": 0,
                    "subscription_revenue": str(item["revenue"] or 0),
                    "subscription_count": item["count"],
                }

        # Sort by date
        result = sorted(data.values(), key=lambda x: x["date"])

        return Response({
            "period": "daily",
            "days": days,
            "data": result,
        })

    def _get_monthly_trend(self, months):
        from subscriptions.models import SubscriptionCharge
        from subscriptions.enums import SubscriptionChargeStatus

        start_date = timezone.now().date() - timedelta(days=months * 30)

        # Order revenue by month
        order_revenue = (
            Order.objects.filter(
                deleted_at__isnull=True,
                order_status=OrderStatus.PAID,
                ordered_at__date__gte=start_date,
            )
            .annotate(month=TruncMonth("ordered_at"))
            .values("month")
            .annotate(revenue=Sum("amount"), count=Count("id"))
            .order_by("month")
        )

        # Subscription revenue by month
        sub_revenue = (
            SubscriptionCharge.objects.filter(
                status=SubscriptionChargeStatus.PAID,
                created_at__date__gte=start_date,
            )
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(revenue=Sum("amount"), count=Count("id"))
            .order_by("month")
        )

        # Merge data
        data = {}
        for item in order_revenue:
            month_str = item["month"].strftime("%Y-%m")
            data[month_str] = {
                "month": month_str,
                "order_revenue": str(item["revenue"] or 0),
                "order_count": item["count"],
                "subscription_revenue": "0.00",
                "subscription_count": 0,
            }

        for item in sub_revenue:
            month_str = item["month"].strftime("%Y-%m")
            if month_str in data:
                data[month_str]["subscription_revenue"] = str(item["revenue"] or 0)
                data[month_str]["subscription_count"] = item["count"]
            else:
                data[month_str] = {
                    "month": month_str,
                    "order_revenue": "0.00",
                    "order_count": 0,
                    "subscription_revenue": str(item["revenue"] or 0),
                    "subscription_count": item["count"],
                }

        result = sorted(data.values(), key=lambda x: x["month"])

        return Response({
            "period": "monthly",
            "months": months,
            "data": result,
        })


@extend_schema(
    tags=["Admin - Dashboard"],
    summary="Admin: Order status breakdown",
    responses={
        200: inline_serializer(
            name="OrderStatusBreakdownResponse",
            fields={
                "breakdown": drf_serializers.ListField(),
            },
        )
    },
)
class AdminOrderStatusBreakdownView(APIView):
    """Get order status breakdown for dashboard."""
    
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get(self, request):
        breakdown = (
            Order.objects.filter(deleted_at__isnull=True)
            .values("order_status")
            .annotate(count=Count("id"), revenue=Sum("amount"))
            .order_by("-count")
        )

        return Response({
            "breakdown": list(breakdown),
        })
