from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from .models import PaymentTransaction
from . import services
from . import serializers as sz


logger = logging.getLogger(__name__)


def _sync_subscription_charge(txn: PaymentTransaction | None) -> None:
    if not txn:
        return
    try:
        from subscriptions.services import sync_charge_from_transaction
    except Exception:
        return
    try:
        sync_charge_from_transaction(txn)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning(
            "Failed to sync subscription charge for transaction %s: %s",
            txn.pk,
            exc,
        )


def _sync_order(txn: PaymentTransaction | None):
    if not txn:
        return None
    try:
        from products.services import sync_order_from_transaction
    except Exception:
        return None
    try:
        return sync_order_from_transaction(txn)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning(
            "Failed to sync order for transaction %s: %s",
            txn.pk,
            exc,
        )
        return None


def _orders_redirect_url() -> str:
    try:
        return reverse("products_page")
    except Exception:
        return reverse("subscriptions:user-dashboard")


def _get_transaction_for_order(order_id: str) -> PaymentTransaction | None:
    if not order_id:
        return None
    return (
        PaymentTransaction.objects.filter(sp_order_id=order_id).first()
        or PaymentTransaction.objects.filter(customer_order_id=order_id).first()
    )


def _extract_payload(verified: Any) -> dict | None:
    if not verified:
        return None
    if isinstance(verified, dict):
        return verified
    return getattr(verified, "__dict__", None)


def _is_successful_verification(verified: Any) -> bool:
    if not verified:
        return False
    status_str = (
        str(
            getattr(verified, "transaction_status", "")
            or getattr(verified, "status", "")
        )
        .strip()
        .lower()
    )
    sp_code = str(getattr(verified, "sp_code", "") or "").strip()
    verification_flag = getattr(verified, "payment_verification_status", None)
    return (
        bool(verification_flag)
        or status_str in {"success", "completed"}
        or sp_code == "1000"
    )


def _update_transaction_from_verification(
    order_id: str, verified: Any
) -> tuple[PaymentTransaction | None, bool, dict | None]:
    txn = _get_transaction_for_order(order_id)
    payload = _extract_payload(verified)
    success = _is_successful_verification(verified)
    if txn:
        txn.verification_payload = payload
        txn.status = (
            PaymentTransaction.Status.SUCCESS
            if success
            else PaymentTransaction.Status.FAILED
        )
        txn.save(update_fields=["status", "verification_payload", "updated_at"])
        _sync_subscription_charge(txn)
        _sync_order(txn)
    return txn, success, payload


class InitiatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["ShurjoPay"],
        summary="Initiate a shurjoPay payment and get checkout URL",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "reference": {
                        "type": "string",
                        "description": "Domain reference, e.g., Order ID",
                    },
                    "amount": {"type": "number"},
                    "currency": {"type": "string", "default": "BDT"},
                    "customer_name": {"type": "string"},
                    "customer_address": {"type": "string"},
                    "customer_phone": {"type": "string"},
                    "customer_city": {"type": "string"},
                    "customer_post_code": {"type": "string"},
                    "customer_email": {"type": "string", "format": "email"},
                },
                "required": ["amount"],
            }
        },
        responses={
            200: OpenApiResponse(description="Checkout URL and identifiers returned"),
            400: None,
            401: None,
        },
    )
    def post(self, request: HttpRequest):
        data: dict[str, Any] = request.data if isinstance(request.data, dict) else {}
        try:
            amount = float(data.get("amount"))
        except Exception:
            return Response(
                {"detail": "amount is required and must be a number"}, status=400
            )
        currency = (data.get("currency") or "BDT").strip() or "BDT"
        ref = (data.get("reference") or "").strip()
        cust = {
            "customer_name": data.get("customer_name", ""),
            "customer_address": data.get("customer_address", ""),
            "customer_phone": data.get("customer_phone", ""),
            "customer_city": data.get("customer_city", ""),
            "customer_post_code": data.get("customer_post_code", ""),
            "customer_email": data.get("customer_email", ""),
        }
        # Determine client IP according to common proxy headers; fallback to REMOTE_ADDR
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        client_ip = (
            xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")
        ) or ""

        # Use a customer_order_id we control (prefix + transaction pk later). For now, pass ref or a generated string.
        order_id = ref or f"U{request.user.id}-TXN"

        with transaction.atomic():
            txn = PaymentTransaction.objects.create(
                user=request.user,
                reference=ref,
                amount=amount,
                currency=currency,
                status=PaymentTransaction.Status.INITIATED,
                request_payload=data,
            )
            # Use txn.pk to make customer_order_id stable and unique
            order_id = ref or f"TXN-{txn.pk}"
            details = services.initiate_payment(
                amount=amount,
                order_id=order_id,
                currency=currency,
                client_ip=client_ip,
                **cust,
            )
            if details is None:
                txn.status = PaymentTransaction.Status.FAILED
                txn.save(update_fields=["status"])
                _sync_subscription_charge(txn)
                return Response({"detail": "Failed to obtain checkout URL"}, status=502)

            # Persist identifiers
            txn.checkout_url = getattr(details, "checkout_url", "")
            txn.sp_order_id = getattr(details, "sp_order_id", "")
            txn.customer_order_id = getattr(details, "customer_order_id", order_id)
            txn.status = (
                PaymentTransaction.Status.REDIRECTED
                if txn.checkout_url
                else PaymentTransaction.Status.INITIATED
            )
            txn.response_payload = details.__dict__
            txn.save()
            _sync_subscription_charge(txn)
            _sync_order(txn)

        return Response(
            {
                "transaction_id": txn.id,
                "checkout_url": txn.checkout_url,
                "sp_order_id": txn.sp_order_id,
                "customer_order_id": txn.customer_order_id,
            }
        )


class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["ShurjoPay"],
        summary="Verify payment by shurjoPay order_id",
        request={
            "application/json": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            }
        },
        responses={
            200: OpenApiResponse(
                description="Verified payment details or null if invalid"
            )
        },
    )
    def post(self, request: HttpRequest):
        order_id = (
            (request.data or {}).get("order_id")
            if isinstance(request.data, dict)
            else request.data
        )
        if not order_id:
            return Response(
                {"detail": "order_id is required"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        try:
            verified = services.verify_payment(order_id)
        except Exception as exc:  # pragma: no cover - SDK/network errors
            logger.warning(
                "shurjoPay verify failed for %s: %s", order_id, exc, exc_info=True
            )
            return Response(
                {"detail": "Verification temporarily unavailable"},
                status=http_status.HTTP_502_BAD_GATEWAY,
            )

        _update_transaction_from_verification(order_id, verified)
        payload = _extract_payload(verified)
        return Response(payload)


class ReturnView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["ShurjoPay"],
        summary="Return URL endpoint (browser redirect)",
        parameters=[
            OpenApiParameter(
                name="order_id",
                location=OpenApiParameter.QUERY,
                required=False,
                type=str,
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: HttpRequest):
        order_id = request.query_params.get("order_id", "").strip()
        info: dict[str, Any] = {
            "order_id": order_id or None,
            "success": False,
            "message": "Payment verification could not be completed.",
        }
        status_code = http_status.HTTP_400_BAD_REQUEST
        redirect_url = reverse("subscriptions:user-dashboard")

        if order_id:
            try:
                verified = services.verify_payment(order_id)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Return verify failed for %s: %s", order_id, exc, exc_info=True
                )
                info["message"] = "We could not verify the payment at this time."
                verified = None
            txn, success, payload = _update_transaction_from_verification(
                order_id, verified
            )
            if txn and (
                (txn.reference or "").startswith("order:")
                or (isinstance(txn.request_payload, dict) and txn.request_payload.get("order_id"))
            ):
                redirect_url = _orders_redirect_url()
            info.update(
                {
                    "success": success,
                    "verified": payload,
                    "transaction_id": txn.id if txn else None,
                }
            )
            if success:
                info["message"] = (payload or {}).get("message") or "Payment successful"
                status_code = http_status.HTTP_200_OK
            elif payload:
                info["message"] = payload.get("message") or info["message"]
        else:
            info["message"] = "order_id is required"

        info["redirect_url"] = redirect_url
        wants_json = (
            getattr(getattr(request, "accepted_renderer", None), "format", None)
            == "json"
            or request.query_params.get("format") == "json"
        )
        if wants_json:
            return Response(info, status=status_code)

        if info["success"]:
            messages.success(request, info["message"])
        else:
            messages.error(request, info["message"])
        return redirect(redirect_url)


class CancelView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["ShurjoPay"],
        summary="Cancel URL endpoint (browser redirect)",
        parameters=[
            OpenApiParameter(
                name="order_id",
                location=OpenApiParameter.QUERY,
                required=False,
                type=str,
            )
        ],
        responses={200: sz.CancelViewResponseSerializer},
    )
    def get(self, request: HttpRequest):
        order_id = request.query_params.get("order_id", "")
        txn = (
            PaymentTransaction.objects.filter(sp_order_id=order_id).first()
            or PaymentTransaction.objects.filter(customer_order_id=order_id).first()
        )
        redirect_url = reverse("subscriptions:user-dashboard")
        if txn:
            txn.status = PaymentTransaction.Status.CANCELLED
            txn.save(update_fields=["status"])
            _sync_subscription_charge(txn)
            _sync_order(txn)
            if (
                (txn.reference or "").startswith("order:")
                or (isinstance(txn.request_payload, dict) and txn.request_payload.get("order_id"))
            ):
                redirect_url = _orders_redirect_url()
        info = {"message": "Payment cancelled", "order_id": order_id or None}
        info["redirect_url"] = redirect_url
        wants_json = (
            getattr(getattr(request, "accepted_renderer", None), "format", None)
            == "json"
            or request.query_params.get("format") == "json"
        )
        if wants_json:
            return Response(info)
        messages.warning(request, "Payment was cancelled before completion.")
        return redirect(redirect_url)


class StatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["ShurjoPay"],
        summary="Get transaction status",
        parameters=[
            OpenApiParameter(
                name="transaction_id",
                location=OpenApiParameter.QUERY,
                required=True,
                type=int,
            )
        ],
        responses={
            200: sz.StatusViewResponseSerializer,
            404: OpenApiResponse(description="Not found"),
        },
    )
    def get(self, request: HttpRequest):
        try:
            txn_id = int(request.query_params.get("transaction_id"))
        except Exception:
            return Response({"detail": "transaction_id is required"}, status=400)
        txn = PaymentTransaction.objects.filter(id=txn_id).first()
        if not txn:
            return Response({"detail": "Not found"}, status=404)
        return Response(
            {
                "id": txn.id,
                "status": txn.status,
                "sp_order_id": txn.sp_order_id,
                "customer_order_id": txn.customer_order_id,
                "checkout_url": txn.checkout_url,
                "amount": str(txn.amount),
                "currency": txn.currency,
                "reference": txn.reference,
                "created_at": txn.created_at,
                "updated_at": txn.updated_at,
            }
        )
