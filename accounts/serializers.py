from rest_framework import serializers

from .models import User
from devices.models import Device


class UserSerializer(serializers.ModelSerializer):
    """Base serializer (kept for backwards compatibility in auth responses)."""

    class Meta:
        model = User
        fields = ("id", "email", "phone_number", "role", "full_name", "address")
        read_only_fields = ("id", "role")


class DeviceSummarySerializer(serializers.ModelSerializer):
    """Minimal device representation for embedding inside user detail."""

    class Meta:
        model = Device
        fields = (
            "id",
            "hardware_identifier",
            "device_name",
            "device_role",
            "latitude",
            "longitude",
            "status",
            "last_seen",
        )
        read_only_fields = fields


class UserDetailSerializer(UserSerializer):
    devices = DeviceSummarySerializer(many=True, read_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ("devices",)


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("full_name", "phone_number", "address")
        extra_kwargs = {
            "full_name": {"required": False, "allow_blank": True},
            "phone_number": {"required": False, "allow_blank": True},
            "address": {"required": False, "allow_blank": True},
        }


class AdminUserUpdateSerializer(UserUpdateSerializer):
    class Meta(UserUpdateSerializer.Meta):
        # Allow admin to also update role (but not arbitrary privilege flags here)
        fields = UserUpdateSerializer.Meta.fields + ("role",)
        extra_kwargs = {
            **UserUpdateSerializer.Meta.extra_kwargs,
            "role": {"required": False},
        }


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    phone_number = serializers.CharField(required=False, allow_blank=True)
