from __future__ import annotations

from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.utils import timezone

from common.permissions import IsOwnerOrSuperadmin
from .models import Package, Order
from .serializers import PackageSerializer, OrderSerializer, OrderCreateSerializer


@extend_schema(tags=["Packages"])
class PackageViewSet(viewsets.ModelViewSet):
    serializer_class = PackageSerializer
    queryset = Package.objects.filter(deleted_at__isnull=True)
    permission_classes = [IsAuthenticated, IsOwnerOrSuperadmin]
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None  # remove page param from schema/results
    lookup_value_regex = r"\d+"

    def destroy(self, request, *args, **kwargs):
        instance: Package = self.get_object()
        instance.deleted_at = timezone.now()
        instance.deleted_by = request.user
        instance.save(update_fields=["deleted_at", "deleted_by"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        return Package.objects.filter(deleted_at__isnull=True)


@extend_schema(tags=["Orders"])
class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrSuperadmin]
    http_method_names = ["get", "post", "patch", "delete"]
    pagination_class = None  # remove page param from schema/results
    queryset = Order.objects.select_related("user", "package").filter(
        deleted_at__isnull=True, package__deleted_at__isnull=True
    )
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        user = self.request.user
        # If anonymous, return empty queryset to avoid AnonymousUser filtering crash
        if not user or not user.is_authenticated:
            return Order.objects.none()
        qs = (
            Order.objects.select_related("user", "package")
            .filter(deleted_at__isnull=True, package__deleted_at__isnull=True)
            .order_by("-ordered_at")
        )
        if not (getattr(user, "role", None) == "superadmin" or user.is_superuser):
            qs = qs.filter(user=user)
        # filters
        package_id = self.request.query_params.get("package")
        status_param = self.request.query_params.get("status")
        if package_id:
            try:
                qs = qs.filter(package_id=int(package_id))
            except Exception:
                pass
        if status_param in {s for s, _ in Order.Status.choices}:
            qs = qs.filter(order_status=status_param)
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderSerializer

    def perform_destroy(self, instance: Order):
        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save(update_fields=["deleted_at", "deleted_by"])

    @extend_schema(
        summary="List orders",
        parameters=[
            OpenApiParameter(
                name="package", description="Package ID", required=False, type=int
            ),
            OpenApiParameter(
                name="status",
                description="Status filter: pending|paid|cancelled|failed",
                required=False,
                type=str,
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        ser = OrderCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        order = ser.save()
        return Response(OrderSerializer(order).data, status=201)

    def update(self, request, *args, **kwargs):
        """Recalculate total_amount if package or quantity changed.
        Allows partial updates (PATCH). Prevents manual tampering of total_amount.
        """
        partial = kwargs.pop("partial", False)
        instance: Order = self.get_object()
        old_package_id = instance.package_id
        old_quantity = instance.quantity

        # Only allow specific mutable fields (ignore attempts to change total_amount, status, etc.)
        mutable_fields = {"package", "quantity", "shipping_address"}
        data = request.data.copy()
        for key in list(data.keys()):
            if key not in mutable_fields:
                data.pop(key)

        ser = OrderSerializer(instance, data=data, partial=partial)
        ser.is_valid(raise_exception=True)
        updated = ser.save()

        if updated.package_id != old_package_id or updated.quantity != old_quantity:
            from decimal import Decimal

            updated.total_amount = updated.package.price_per_device * Decimal(
                updated.quantity
            )
            updated.save(update_fields=["total_amount"])

        return Response(OrderSerializer(updated).data)
