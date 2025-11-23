from __future__ import annotations

from rest_framework import serializers

from devices.models import Device
from .models import DeviceSubscription, SubscriptionCharge


class DeviceSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        ref_name = "SubscriptionDeviceSummary"
        fields = (
            "id",
            "hardware_identifier",
            "device_name",
            "device_role",
            "status",
        )


class SubscriptionChargeSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    device_id = serializers.IntegerField(
        source="subscription.device.id", read_only=True
    )
    device_name = serializers.CharField(
        source="subscription.device.device_name", read_only=True
    )

    class Meta:
        model = SubscriptionCharge
        fields = (
            "id",
            "device_id",
            "device_name",
            "amount",
            "cycles",
            "status",
            "status_display",
            "period_start",
            "period_end",
            "provider_reference",
            "is_manual",
            "created_at",
            "updated_at",
        )


class DeviceSubscriptionSerializer(serializers.ModelSerializer):
    device = DeviceSummarySerializer(read_only=True)
    days_remaining = serializers.SerializerMethodField()
    is_accessible = serializers.SerializerMethodField()

    class Meta:
        model = DeviceSubscription
        fields = (
            "id",
            "device",
            "status",
            "monthly_amount",
            "billing_anchor",
            "last_paid_through",
            "next_due_at",
            "grace_expires_at",
            "admin_override_until",
            "days_remaining",
            "is_accessible",
        )

    def get_days_remaining(self, obj: DeviceSubscription) -> int:
        if not obj.last_paid_through:
            return 0
        from django.utils import timezone

        now = timezone.now()
        delta = obj.last_paid_through - now
        return max(delta.days, 0)

    def get_is_accessible(self, obj: DeviceSubscription) -> bool:
        return obj.is_active_for_user


class AdminDeviceSubscriptionSerializer(DeviceSubscriptionSerializer):
    owner_email = serializers.EmailField(source="device.user.email", read_only=True)
    owner_id = serializers.IntegerField(source="device.user.id", read_only=True)

    class Meta(DeviceSubscriptionSerializer.Meta):
        fields = DeviceSubscriptionSerializer.Meta.fields + (
            "owner_email",
            "owner_id",
        )


class SubscriptionTopUpSerializer(serializers.Serializer):
    months = serializers.IntegerField(min_value=1, max_value=24, default=1)


class SubscriptionOverrideSerializer(serializers.Serializer):
    admin_override_until = serializers.DateTimeField(required=False, allow_null=True)


class ManualPaymentSerializer(serializers.Serializer):
    months = serializers.IntegerField(min_value=1, max_value=24, default=1)
    note = serializers.CharField(required=False, allow_blank=True)
