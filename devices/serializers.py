from rest_framework import serializers
from decimal import Decimal

from .models import Device, Telemetry, Alert


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = (
            "id",
            "hardware_identifier",
            "device_name",
            "latitude",
            "longitude",
            "status",
            "registered_at",
            "last_seen",
        )
        read_only_fields = ("id", "registered_at", "last_seen")


class DeviceRegisterSerializer(serializers.Serializer):
    hardware_identifier = serializers.CharField(max_length=64)
    device_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)

    def validate(self, attrs):
        lat = attrs.get("latitude")
        lon = attrs.get("longitude")
        if lat is None or lon is None:
            raise serializers.ValidationError("latitude and longitude are required")
        if not (Decimal("-90") <= lat <= Decimal("90")):
            raise serializers.ValidationError("latitude must be between -90 and 90")
        if not (Decimal("-180") <= lon <= Decimal("180")):
            raise serializers.ValidationError("longitude must be between -180 and 180")
        return attrs


class TelemetrySerializer(serializers.ModelSerializer):
    device_id = serializers.PrimaryKeyRelatedField(
        source="device", queryset=Device.objects.all(), write_only=True
    )
    device = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Telemetry
        fields = (
            "id",
            "device_id",
            "device",
            "smoke_level",
            "device_status",
            "timestamp",
            "received_at",
        )
        read_only_fields = ("id", "received_at")


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = (
            "id",
            "device",
            "alert_type",
            "status",
            "triggered_at",
            "resolved_at",
        )
        read_only_fields = ("id", "triggered_at", "resolved_at")
