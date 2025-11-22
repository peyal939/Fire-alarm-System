from __future__ import annotations

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from django.utils import timezone
from django.db import models
from common.permissions import IsOwnerOrSuperadmin
from .enums import OrderStatus
from .models import Package, Order
from .serializers import PackageSerializer, OrderSerializer, OrderCreateSerializer

# ensure signals are imported / registered
from . import signals


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
        instance.updated_by = request.user
        instance.save(update_fields=["deleted_at", "deleted_by", "updated_by"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        return Package.objects.filter(deleted_at__isnull=True)

    def perform_update(self, serializer):  # ensure updated_by is tracked
        serializer.save(updated_by=self.request.user)


def _apply_order_patch(instance: Order, data: dict, user=None) -> Order:
    """Internal helper to apply mutable field updates and recalc amount when needed.
    Mutable fields:
      - package
      - quantity
      - shipping_address
      - number_of_master_devices
      - number_of_slave_devices
    """
    from decimal import Decimal

    old_package_id = instance.package_id
    old_quantity = instance.quantity
    mutable_fields = {
        "package",
        "quantity",
        "shipping_address",
        "number_of_master_devices",
        "number_of_slave_devices",
    }
    cleaned = {}
    for key, value in data.items():
        if key in mutable_fields:
            cleaned[key] = value
    ser = OrderSerializer(instance, data=cleaned, partial=True)
    ser.is_valid(raise_exception=True)
    updated = ser.save()
    fields_to_update = []
    if updated.package_id != old_package_id or updated.quantity != old_quantity:
        updated.amount = updated.package.price_per_device * Decimal(updated.quantity)
        fields_to_update.append("amount")
    if user is not None and getattr(user, "is_authenticated", False):
        updated.updated_by = user
        fields_to_update.append("updated_by")
    if fields_to_update:
        updated.save(update_fields=fields_to_update)
    return updated


@extend_schema(
    tags=["Orders"],
    summary="Payment notification webhook - receive provider order id to mark pending order paid",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "transaction_id": {"type": "string"},
                "gateway_response": {"type": "object"},
            },
            "required": ["order_id"],
        }
    },
    responses={200: None, 400: None},
)
class OrderIdNotifyView(APIView):
    """
    Webhook to receive the provider (SurjoPay) order id after successful payment.

    Expected JSON:
      {
        "order_id": "provider-generated-id-or-our-integer-id",
        "transaction_id": "tx_abc123",         # optional
        "gateway_response": {...}              # optional
      }

    This sends the `payment_received` signal. A receiver will mark the order
    as paid if it is currently pending.
    """

    authentication_classes = []  # adjust if you want auth
    permission_classes = []  # open endpoint; adjust if needed

    def post(self, request):
        if not isinstance(request.data, dict):
            return Response({"detail": "Payload must be an object"}, status=400)
        provider_order_id = request.data.get("order_id")
        if not provider_order_id:
            return Response({"detail": "order_id is required"}, status=400)
        transaction_id = request.data.get("transaction_id")
        gateway_response = request.data.get("gateway_response", None)

        # Fire signal; receiver will update DB if matching pending orders exist
        from .signals import payment_received

        payment_received.send(
            sender=self.__class__,
            provider_order_id=str(provider_order_id),
            transaction_id=transaction_id,
            gateway_response=gateway_response,
        )

        # indicate whether any order was marked paid
        marked_paid = (
            Order.objects.filter(deleted_at__isnull=True, order_status=OrderStatus.PAID)
            .filter(
                models.Q(reference=str(provider_order_id))
                | models.Q(
                    id__exact=(
                        provider_order_id if str(provider_order_id).isdigit() else None
                    )
                )
            )
            .exists()
        )
        return Response(
            {"provider_order_id": provider_order_id, "marked_paid": marked_paid},
            status=200,
        )


@extend_schema(
    tags=["Orders"],
    summary="List / create / patch / delete orders for a user",
    responses={
        200: OrderSerializer(many=True),
        201: OrderSerializer,
        400: None,
        401: None,
        403: None,
        404: None,
    },
)
class UserOrderListView(APIView):
    """Endpoint: /orders/<user_id>/

    Methods:
        GET    /orders/<user_id>/  -> list user's orders (?package=&status= filters)
        POST   /orders/<user_id>/  -> create order
        PATCH  /orders/<user_id>/  -> patch ONE order (order_id provided in body)
        DELETE /orders/<user_id>/  -> soft delete all (non-deleted) orders of user

    PATCH body format (Option B):
        {
            "order_id": 10,
            "quantity": 15,              # optional
            "shipping_address": "Updated address"  # optional
        }

    Mutable fields at this endpoint:
        - quantity
        - shipping_address
        - number_of_master_devices
        - number_of_slave_devices
    """

    permission_classes = [IsOwnerOrSuperadmin]

    def _auth_user_allowed(self, request_user, target_user_id: int) -> bool:
        return bool(
            request_user
            and request_user.is_authenticated
            and (
                request_user.is_superuser
                or getattr(request_user, "role", None) == "superadmin"
                or str(request_user.id) == str(target_user_id)
            )
        )

    def get(self, request, user_id: int):
        if not self._auth_user_allowed(request.user, user_id):
            if not request.user or not request.user.is_authenticated:
                return Response({"detail": "Authentication required"}, status=401)
            return Response({"detail": "Forbidden"}, status=403)
        qs = (
            Order.objects.select_related("user", "package")
            .filter(
                user_id=user_id,
                deleted_at__isnull=True,
                package__deleted_at__isnull=True,
            )
            .order_by("-ordered_at")
        )
        package_id = request.query_params.get("package")
        status_param = request.query_params.get("status")
        if package_id:
            try:
                qs = qs.filter(package_id=int(package_id))
            except Exception:
                pass
        if status_param in {s for s, _ in OrderStatus.choices}:
            qs = qs.filter(order_status=status_param)
        return Response(OrderSerializer(qs, many=True).data)

    @extend_schema(
        summary="Create order for user",
        request=OrderCreateSerializer,
        responses={201: OrderSerializer, 400: None, 401: None, 403: None},
    )
    def post(self, request, user_id: int):
        if not self._auth_user_allowed(request.user, user_id):
            if not request.user or not request.user.is_authenticated:
                return Response({"detail": "Authentication required"}, status=401)
            return Response({"detail": "Forbidden"}, status=403)
        if str(request.user.id) != str(user_id) and not (
            request.user.is_superuser
            or getattr(request.user, "role", None) == "superadmin"
        ):
            return Response({"detail": "Forbidden"}, status=403)
        ser = OrderCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        order = ser.save()
        return Response(OrderSerializer(order).data, status=201)

    @extend_schema(
        summary="Patch one order for a user",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer"},
                    "quantity": {"type": "integer", "minimum": 1},
                    "shipping_address": {"type": "string"},
                    "number_of_master_devices": {"type": "integer", "minimum": 0},
                    "number_of_slave_devices": {"type": "integer", "minimum": 0},
                },
                "required": ["order_id"],
            }
        },
        responses={200: OrderSerializer, 400: None, 401: None, 403: None, 404: None},
    )
    @extend_schema(operation_id="orders_partial_update_for_user")
    def patch(self, request, user_id: int):
        if not self._auth_user_allowed(request.user, user_id):
            if not request.user or not request.user.is_authenticated:
                return Response({"detail": "Authentication required"}, status=401)
            return Response({"detail": "Forbidden"}, status=403)
        if not isinstance(request.data, dict):
            return Response({"detail": "Payload must be an object"}, status=400)
        order_id = request.data.get("order_id")
        if not order_id:
            return Response({"detail": "order_id is required"}, status=400)
        try:
            order = Order.objects.select_related("package").get(
                id=order_id,
                user_id=user_id,
                deleted_at__isnull=True,
                package__deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return Response({"detail": "Not found"}, status=404)
        update_data = {}
        if "quantity" in request.data:
            update_data["quantity"] = request.data["quantity"]
        if "shipping_address" in request.data:
            update_data["shipping_address"] = request.data["shipping_address"]
        if "number_of_master_devices" in request.data:
            update_data["number_of_master_devices"] = request.data[
                "number_of_master_devices"
            ]
        if "number_of_slave_devices" in request.data:
            update_data["number_of_slave_devices"] = request.data[
                "number_of_slave_devices"
            ]
        if not update_data:
            return Response({"detail": "No mutable fields provided"}, status=400)
        updated = _apply_order_patch(order, update_data, user=request.user)
        return Response(OrderSerializer(updated).data, status=200)

    @extend_schema(operation_id="orders_delete_all_for_user")
    def delete(self, request, user_id: int):
        if not self._auth_user_allowed(request.user, user_id):
            if not request.user or not request.user.is_authenticated:
                return Response({"detail": "Authentication required"}, status=401)
            return Response({"detail": "Forbidden"}, status=403)
        qs = Order.objects.filter(user_id=user_id, deleted_at__isnull=True)
        now = timezone.now()
        updated = qs.update(
            deleted_at=now, deleted_by=request.user, updated_by=request.user
        )
        return Response({"deleted": updated}, status=200)


@extend_schema(
    tags=["Orders"],
    summary="Retrieve/patch/delete a user's specific order",
    responses={
        200: OrderSerializer,
        204: None,
        400: None,
        401: None,
        403: None,
        404: None,
    },
)
class UserOrderDetailView(APIView):
    permission_classes = [IsOwnerOrSuperadmin]

    def _get_order(self, user_id: int, order_id: int, request_user):
        try:
            order = Order.objects.select_related("package").get(
                id=order_id,
                user_id=user_id,
                deleted_at__isnull=True,
                package__deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return None
        # Permission: owner or superadmin
        if not (
            request_user.is_superuser
            or getattr(request_user, "role", None) == "superadmin"
            or order.user_id == request_user.id
        ):
            return "forbidden"
        return order

    def get(self, request, user_id: int, order_id: int):
        if not request.user or not request.user.is_authenticated:
            return Response({"detail": "Authentication required"}, status=401)
        res = self._get_order(user_id, order_id, request.user)
        if res is None:
            return Response({"detail": "Not found"}, status=404)
        if res == "forbidden":
            return Response({"detail": "Forbidden"}, status=403)
        return Response(OrderSerializer(res).data)

    @extend_schema(
        summary="Patch specific order (quantity / shipping_address / number_of_master_devices / number_of_slave_devices)",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "quantity": {"type": "integer", "minimum": 1},
                    "shipping_address": {"type": "string"},
                    "number_of_master_devices": {"type": "integer", "minimum": 0},
                    "number_of_slave_devices": {"type": "integer", "minimum": 0},
                },
            }
        },
        responses={200: OrderSerializer, 400: None, 401: None, 403: None, 404: None},
    )
    @extend_schema(operation_id="orders_partial_update_for_user_detail")
    def patch(self, request, user_id: int, order_id: int):
        if not request.user or not request.user.is_authenticated:
            return Response({"detail": "Authentication required"}, status=401)
        res = self._get_order(user_id, order_id, request.user)
        if res is None:
            return Response({"detail": "Not found"}, status=404)
        if res == "forbidden":
            return Response({"detail": "Forbidden"}, status=403)
        if not isinstance(request.data, dict):
            return Response({"detail": "Payload must be an object"}, status=400)
        update_data = {}
        if "quantity" in request.data:
            update_data["quantity"] = request.data["quantity"]
        if "shipping_address" in request.data:
            update_data["shipping_address"] = request.data["shipping_address"]
        if "number_of_master_devices" in request.data:
            update_data["number_of_master_devices"] = request.data[
                "number_of_master_devices"
            ]
        if "number_of_slave_devices" in request.data:
            update_data["number_of_slave_devices"] = request.data[
                "number_of_slave_devices"
            ]
        if not update_data:
            return Response({"detail": "No mutable fields provided"}, status=400)
        updated = _apply_order_patch(res, update_data, user=request.user)
        return Response(OrderSerializer(updated).data, status=200)

    @extend_schema(operation_id="orders_destroy_for_user_detail")
    def delete(self, request, user_id: int, order_id: int):
        if not request.user or not request.user.is_authenticated:
            return Response({"detail": "Authentication required"}, status=401)
        res = self._get_order(user_id, order_id, request.user)
        if res is None:
            return Response({"detail": "Not found"}, status=404)
        if res == "forbidden":
            return Response({"detail": "Forbidden"}, status=403)
        res.deleted_at = timezone.now()
        res.deleted_by = request.user
        res.updated_by = request.user
        res.save(update_fields=["deleted_at", "deleted_by", "updated_by"])
        return Response(status=204)


@extend_schema(
    tags=["Orders"],
    summary="Admin: update order status",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "order_status": {
                    "type": "string",
                    "enum": [s for s, _ in OrderStatus.choices],
                    "description": "New status (pending, paid, cancelled, failed, delivered)",
                }
            },
            "required": ["order_status"],
        }
    },
    responses={200: OrderSerializer, 400: None, 401: None, 403: None, 404: None},
)
class AdminOrderStatusUpdateView(APIView):
    """Endpoint: /orders/update_status/<user_id>/<order_id>/

    Admin-only endpoint to update the order_status of a specific order.

    Body:
      { "order_status": "paid" }
    """

    permission_classes = [IsAuthenticated]

    def _is_admin(self, user) -> bool:
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or getattr(user, "role", None) == "superadmin")
        )

    def post(self, request, user_id: int, order_id: int):
        if not self._is_admin(request.user):
            if not request.user or not request.user.is_authenticated:
                return Response({"detail": "Authentication required"}, status=401)
            return Response({"detail": "Forbidden"}, status=403)
        if not isinstance(request.data, dict):
            return Response({"detail": "Payload must be an object"}, status=400)
        new_status = request.data.get("order_status")
        valid_statuses = {s for s, _ in OrderStatus.choices}
        if not new_status or new_status not in valid_statuses:
            return Response(
                {
                    "detail": "Invalid order_status",
                    "allowed": sorted(list(valid_statuses)),
                },
                status=400,
            )
        try:
            order = Order.objects.select_related("package").get(
                id=order_id,
                user_id=user_id,
                deleted_at__isnull=True,
                package__deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return Response({"detail": "Not found"}, status=404)

        # Update only if different
        if order.order_status != new_status:
            order.order_status = new_status
            order.updated_by = request.user
            order.save(update_fields=["order_status", "updated_by"])

        return Response(OrderSerializer(order).data, status=200)
