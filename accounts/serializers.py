from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
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


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(
        write_only=True, trim_whitespace=False, min_length=6
    )
    confirm_new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value: str) -> str:
        user = self.context.get("request").user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs: dict) -> dict:
        new_password = attrs.get("new_password")
        confirm_new_password = attrs.get("confirm_new_password")
        if new_password != confirm_new_password:
            raise serializers.ValidationError(
                {"confirm_new_password": "New password entries do not match."}
            )

        if attrs["current_password"] == new_password:
            raise serializers.ValidationError(
                {
                    "new_password": "New password must be different from the current password."
                }
            )

        user = self.context.get("request").user
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from exc

        return attrs
