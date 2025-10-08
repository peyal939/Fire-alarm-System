from __future__ import annotations

from rest_framework import serializers


class InitiatePaymentRequestSerializer(serializers.Serializer):
    reference = serializers.CharField(required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField(required=False, default="BDT")
    customer_name = serializers.CharField(required=False, allow_blank=True)
    customer_address = serializers.CharField(required=False, allow_blank=True)
    customer_phone = serializers.CharField(required=False, allow_blank=True)
    customer_city = serializers.CharField(required=False, allow_blank=True)
    customer_post_code = serializers.CharField(required=False, allow_blank=True)
    customer_email = serializers.EmailField(required=False, allow_blank=True)


class InitiatePaymentResponseSerializer(serializers.Serializer):
    transaction_id = serializers.IntegerField()
    checkout_url = serializers.URLField(allow_blank=True)
    sp_order_id = serializers.CharField(allow_blank=True)
    customer_order_id = serializers.CharField(allow_blank=True)


class VerifyPaymentRequestSerializer(serializers.Serializer):
    order_id = serializers.CharField()


class VerifyPaymentResponseSerializer(serializers.Serializer):
    # This is intentionally loose because upstream SDK structure may vary.
    # We surface raw dict fields dynamically, but allow unknown keys by not strictly modeling them.
    # For schema clarity expose a few common fields.
    sp_code = serializers.CharField(required=False, allow_blank=True)
    transaction_status = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
    amount = serializers.CharField(required=False, allow_blank=True)


class ReturnViewResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    order_id = serializers.CharField(required=False, allow_blank=True)
    verified = serializers.BooleanField(required=False)
    details = serializers.DictField(required=False)


class CancelViewResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    order_id = serializers.CharField(allow_null=True, required=False, allow_blank=True)


class StatusViewResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    sp_order_id = serializers.CharField(allow_blank=True)
    customer_order_id = serializers.CharField(allow_blank=True)
    checkout_url = serializers.CharField(allow_blank=True)
    amount = serializers.CharField()
    currency = serializers.CharField()
    reference = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
