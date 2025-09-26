from rest_framework import serializers

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
