from __future__ import annotations

import logging

from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.permissions import IsSuperAdmin, IsSuperAdminOrCompanyAdmin
from .models import DeviceSubscription, SubscriptionCharge
from . import services
from .serializers import (
    AdminDeviceSubscriptionSerializer,
    DeviceSubscriptionSerializer,
    ManualPaymentSerializer,
    SubscriptionChargeSerializer,
    SubscriptionOverrideSerializer,
    SubscriptionTopUpSerializer,
)


logger = logging.getLogger(__name__)


class UserSubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """Endpoints for device owners to inspect and top up subscriptions."""

    serializer_class = DeviceSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = DeviceSubscription.objects.select_related(
            "device",
            "device__user",
        ).filter(device__deleted_at__isnull=True)
        user = self.request.user
        filters = Q(device__user=user)
        if getattr(user, "role", "") == "company_admin":
            filters |= Q(device__originating_order__user=user)
        return qs.filter(filters).order_by("-next_due_at", "pk")

    @action(detail=True, methods=["get"], url_path="charges", url_name="charges")
    def list_charges(self, request, pk=None):
        subscription = self.get_object()
        charges = subscription.charges.order_by("-created_at")[:25]
        data = SubscriptionChargeSerializer(charges, many=True).data
        return Response(data)

    @action(detail=True, methods=["post"], url_path="topup", url_name="topup")
    def top_up(self, request, pk=None):
        subscription = self.get_object()
        serializer = SubscriptionTopUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        months = serializer.validated_data["months"]
        logger.info(
            "API pay-now requested",
            extra={
                "user_id": getattr(request.user, "pk", None),
                "subscription_id": subscription.pk,
                "months": months,
            },
        )
        charge = services.create_charge_for_subscription(
            subscription,
            allow_prepay=True,
            auto_initiate=False,
            cycles=months,
        )
        if not charge:
            logger.warning(
                "API pay-now charge creation failed",
                extra={
                    "user_id": getattr(request.user, "pk", None),
                    "subscription_id": subscription.pk,
                    "months": months,
                },
            )
            return Response(
                {"detail": "Unable to create a new charge right now."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client_ip = request.META.get("REMOTE_ADDR", "")
        txn = services.initiate_payment_for_charge(
            charge,
            client_ip=client_ip,
        )
        if txn and txn.checkout_url:
            logger.info(
                "API pay-now redirect ready",
                extra={
                    "user_id": getattr(request.user, "pk", None),
                    "subscription_id": subscription.pk,
                    "charge_id": charge.pk,
                    "transaction_id": getattr(txn, "pk", None),
                    "checkout_url": txn.checkout_url,
                    "client_ip": client_ip,
                },
            )
        else:
            logger.warning(
                "API pay-now missing checkout URL",
                extra={
                    "user_id": getattr(request.user, "pk", None),
                    "subscription_id": subscription.pk,
                    "charge_id": charge.pk,
                    "transaction_id": getattr(txn, "pk", None) if txn else None,
                    "client_ip": client_ip,
                },
            )
        payload = {
            "charge": SubscriptionChargeSerializer(charge).data,
            "checkout_url": getattr(txn, "checkout_url", ""),
            "transaction_id": getattr(txn, "id", None),
        }
        return Response(payload, status=status.HTTP_201_CREATED)


class AdminSubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """Superadmin endpoints for managing billing state."""

    serializer_class = AdminDeviceSubscriptionSerializer
    permission_classes = [IsAuthenticated, IsSuperAdminOrCompanyAdmin]

    def get_queryset(self):
        qs = DeviceSubscription.objects.select_related(
            "device",
            "device__user",
        ).order_by("-next_due_at", "pk")
        user = self.request.user
        role = getattr(user, "role", "")
        if user.is_superuser or role == "superadmin":
            base = qs
        elif role == "company_admin":
            base = qs.filter(
                Q(device__user=user) | Q(device__originating_order__user=user)
            )
        else:
            base = qs.none()
        status_q = self.request.query_params.get("status")
        query = self.request.query_params.get("q", "").strip()
        if status_q:
            base = base.filter(status=status_q)
        if query:
            base = base.filter(
                Q(device__hardware_identifier__icontains=query)
                | Q(device__device_name__icontains=query)
                | Q(device__user__email__icontains=query)
            )
        return base

    @action(detail=True, methods=["post"], url_path="override", url_name="override")
    def set_override(self, request, pk=None):
        subscription = self.get_object()
        serializer = SubscriptionOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subscription.admin_override_until = serializer.validated_data.get(
            "admin_override_until"
        )
        subscription.save(update_fields=["admin_override_until"])
        return Response(
            {
                "subscription": AdminDeviceSubscriptionSerializer(subscription).data,
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="manual-payment",
        url_name="manual-payment",
    )
    def manual_payment(self, request, pk=None):
        subscription = self.get_object()
        serializer = ManualPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        charge = services.apply_manual_payment(
            subscription,
            months=serializer.validated_data.get("months", 1),
            note=serializer.validated_data.get("note", ""),
            actor=request.user,
        )
        if not charge:
            return Response(
                {"detail": "Unable to record manual payment."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "subscription": AdminDeviceSubscriptionSerializer(subscription).data,
                "charge": SubscriptionChargeSerializer(charge).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="charges", url_name="charges")
    def admin_charges(self, request, pk=None):
        subscription = self.get_object()
        charges = subscription.charges.order_by("-created_at")[:50]
        data = SubscriptionChargeSerializer(charges, many=True).data
        return Response(data)
