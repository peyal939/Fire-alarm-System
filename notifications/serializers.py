"""Serializers for FCM device registration and notification endpoints."""

from rest_framework import serializers
from .models import FCMDevice, NotificationLog


class FCMDeviceSerializer(serializers.ModelSerializer):
    """Serializer for FCM device registration."""

    class Meta:
        model = FCMDevice
        fields = [
            "id",
            "registration_token",
            "device_name",
            "device_type",
            "active",
            "created_at",
            "updated_at",
            "last_used_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "last_used_at"]

    def validate_registration_token(self, value):
        """Ensure token is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("Registration token cannot be empty")
        return value.strip()

    def create(self, validated_data):
        """Create or update FCM device token for the user."""
        user = self.context["request"].user
        token = validated_data["registration_token"]
        import hashlib

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

        # Check if this token already exists
        existing = FCMDevice.objects.filter(registration_token_hash=token_hash).first()

        if existing:
            # Update existing token (in case user changed)
            existing.user = user
            existing.device_name = validated_data.get(
                "device_name", existing.device_name
            )
            existing.device_type = validated_data.get(
                "device_type", existing.device_type
            )
            existing.active = True  # Reactivate if it was deactivated
            existing.registration_token = token
            existing.save()
            return existing

        # Create new token
        validated_data["user"] = user
        return super().create(validated_data)


class NotificationLogSerializer(serializers.ModelSerializer):
    """Serializer for notification history."""

    device_name = serializers.CharField(source="fcm_device.device_name", read_only=True)

    class Meta:
        model = NotificationLog
        fields = [
            "id",
            "title",
            "body",
            "data",
            "status",
            "error_message",
            "sent_at",
            "device_name",
        ]
        read_only_fields = fields


class TestNotificationSerializer(serializers.Serializer):
    """Serializer for sending test notifications."""

    message = serializers.CharField(
        max_length=500,
        required=False,
        default="Test notification from Fire Alarm System",
    )
