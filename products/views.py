from __future__ import annotations

from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from django.utils import timezone
from django.db import models
from common.permissions import IsOwnerOrSuperadmin, IsSuperAdmin
from .enums import OrderStatus
from .models import Package, Order
from .serializers import PackageSerializer, OrderSerializer, OrderCreateSerializer
from . import services as order_services
from django.shortcuts import get_object_or_404

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
        updated.amount = order_services.calculate_order_total(
            updated.package,
            updated.quantity,
        )
        fields_to_update.append("amount")
    if user is not None and getattr(user, "is_authenticated", False):
        updated.updated_by = user
        fields_to_update.append("updated_by")
    if fields_to_update:
        updated.save(update_fields=fields_to_update)
    return updated


@extend_schema(
    tags=["Orders"],
    summary="Admin: list all active orders",
    responses={
        200: OrderSerializer(many=True),
        401: None,
        403: None,
    },
)
class OrderListAllView(APIView):
    """Admin-only endpoint to list every non-deleted order."""

    permission_classes = [IsSuperAdmin]

    def get(self, request):
        qs = (
            Order.objects.select_related("user", "package")
            .filter(deleted_at__isnull=True, package__deleted_at__isnull=True)
            .order_by("-ordered_at")
        )
        status_param = request.query_params.get("status")
        if status_param in {s for s, _ in Order.Status.choices}:
            qs = qs.filter(order_status=status_param)
        package_id = request.query_params.get("package")
        if package_id:
            try:
                qs = qs.filter(package_id=int(package_id))
            except (TypeError, ValueError):
                pass
        user_id = request.query_params.get("user")
        if user_id:
            try:
                qs = qs.filter(user_id=int(user_id))
            except (TypeError, ValueError):
                pass
        return Response(OrderSerializer(qs, many=True).data)


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
        if request.user.is_superuser or getattr(request.user, "role", "") == "superadmin":
            return Response(
                {
                    "detail": "Admin or super admin can't create any order. Only User can create order.",
                },
                status=403,
            )
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
    summary="Initiate payment for an order",
    responses={
        201: {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "integer"},
                "checkout_url": {"type": "string", "format": "uri"},
                "sp_order_id": {"type": "string"},
                "customer_order_id": {"type": "string"},
            },
        },
        400: None,
        401: None,
        403: None,
        404: None,
        502: None,
    },
)
class OrderPaymentInitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id: int, order_id: int):
        if not request.user or not request.user.is_authenticated:
            return Response({"detail": "Authentication required"}, status=401)
        if str(request.user.id) != str(user_id):
            return Response({"detail": "Forbidden"}, status=403)
        try:
            order = Order.objects.select_related("user", "package").get(
                id=order_id,
                user_id=user_id,
                deleted_at__isnull=True,
                package__deleted_at__isnull=True,
            )
        except Order.DoesNotExist:
            return Response({"detail": "Not found"}, status=404)
        if order.order_status == Order.Status.PAID:
            return Response({"detail": "Order is already paid."}, status=400)
        if order.amount is None or order.amount <= 0:
            return Response(
                {"detail": "Order amount must be greater than zero."},
                status=400,
            )
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        client_ip = (
            xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")
        )
        txn = order_services.initiate_payment_for_order(
            order,
            client_ip=client_ip or "",
            actor=request.user,
        )
        if not txn or not txn.checkout_url:
            return Response(
                {"detail": "Unable to start payment. Please try again later."},
                status=502,
            )
        return Response(
            {
                "transaction_id": txn.id,
                "checkout_url": txn.checkout_url,
                "sp_order_id": txn.sp_order_id,
                "customer_order_id": txn.customer_order_id,
            },
            status=201,
        )


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


@extend_schema(
    tags=["Orders"],
    summary="Admin: fulfill an order by assigning hardware IDs",
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "master_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "slave_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["master_ids", "slave_ids"],
        }
    },
    responses={200: None, 400: None, 401: None, 403: None, 404: None},
)
class OrderFulfillView(APIView):
    """Admin-only endpoint to fulfill an order by assigning hardware IDs."""
    permission_classes = [IsSuperAdmin]

    def post(self, request, user_id, order_id):
        # Ensure order belongs to the user specified in URL (or just ignore user_id if we trust order_id unique)
        # Using user_id adds a layer of safety/consistency with other URLs
        order = get_object_or_404(Order, pk=order_id, user_id=user_id)
        
        master_ids = request.data.get('master_ids', [])
        slave_data = request.data.get('slave_data', [])
        
        # Legacy support or simple list handling if needed, but UI will send structured data
        # If master_ids is string, split it
        if isinstance(master_ids, str):
            master_ids = [x.strip() for x in master_ids.splitlines() if x.strip()]
            
        # If slave_data is not provided but slave_ids is (legacy/textarea fallback)
        if not slave_data and 'slave_ids' in request.data:
            slave_ids_raw = request.data.get('slave_ids')
            if isinstance(slave_ids_raw, str):
                slave_ids_list = [x.strip() for x in slave_ids_raw.splitlines() if x.strip()]
                slave_data = [{'id': x, 'master_id': None} for x in slave_ids_list]
            elif isinstance(slave_ids_raw, list):
                slave_data = [{'id': x, 'master_id': None} for x in slave_ids_raw]

        try:
            order_services.fulfill_order(order, master_ids, slave_data, actor=request.user)
            return Response({"detail": "Order fulfilled successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
