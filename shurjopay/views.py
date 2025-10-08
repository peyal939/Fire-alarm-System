from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import HttpRequest
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from .models import PaymentTransaction
from . import services
from . import serializers as sz


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
            else None
        )
        if not order_id:
            return Response({"detail": "order_id is required"}, status=400)
        verified = services.verify_payment(order_id)

        # Best-effort: update matching transaction
        txn = (
            PaymentTransaction.objects.filter(sp_order_id=order_id).first()
            or PaymentTransaction.objects.filter(customer_order_id=order_id).first()
        )
        if txn:
            txn.verification_payload = getattr(verified, "__dict__", None)
            if verified is None:
                # No such order id
                txn.status = PaymentTransaction.Status.FAILED
            else:
                # Null-safe status detection and support sp_code "1000"
                status_raw = (
                    getattr(verified, "transaction_status", None)
                    or getattr(verified, "status", None)
                    or ""
                )
                status_str = str(status_raw).lower()
                sp_code_val = getattr(verified, "sp_code", None)
                sp_code_str = str(sp_code_val) if sp_code_val is not None else None
                is_success = (
                    getattr(verified, "payment_verification_status", False)
                    or status_str == "success"
                    or status_str == "completed"
                    or sp_code_str == "1000"
                )
                txn.status = (
                    PaymentTransaction.Status.SUCCESS
                    if is_success
                    else PaymentTransaction.Status.FAILED
                )
            txn.save()

        return Response(verified.__dict__ if verified else None)


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
        info: dict[str, Any] = {"message": "Return received"}
        if order_id:
            info["order_id"] = order_id
            verified = services.verify_payment(order_id)
            info["verified"] = bool(verified)
            if verified:
                info["details"] = getattr(verified, "__dict__", None)
            # Update transaction best-effort
            txn = (
                PaymentTransaction.objects.filter(sp_order_id=order_id).first()
                or PaymentTransaction.objects.filter(customer_order_id=order_id).first()
            )
            if txn:
                payload = getattr(verified, "__dict__", None)
                txn.verification_payload = payload
                is_success = False
                if verified:
                    # Accept multiple success indicators from SDK or raw API
                    status_str = (
                        getattr(verified, "transaction_status", "")
                        or getattr(verified, "status", "")
                    ).lower()
                    sp_code_val = getattr(verified, "sp_code", None)
                    sp_code_str = str(sp_code_val) if sp_code_val is not None else None
                    is_success = (
                        getattr(verified, "payment_verification_status", False)
                        or status_str == "success"
                        or status_str == "completed"
                        or sp_code_str == "1000"
                    )
                txn.status = (
                    PaymentTransaction.Status.SUCCESS
                    if is_success
                    else PaymentTransaction.Status.FAILED
                )
                txn.save()
        return Response(info)


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
        if txn:
            txn.status = PaymentTransaction.Status.CANCELLED
            txn.save(update_fields=["status"])
        return Response({"message": "Payment cancelled", "order_id": order_id or None})


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
