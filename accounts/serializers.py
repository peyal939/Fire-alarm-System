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
        ref_name = "AccountDeviceSummary"
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


class RegistrationInitSerializer(serializers.Serializer):
    email = serializers.EmailField()
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)
    full_name = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=["user", "company_admin"], required=False, default="user"
    )

    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError("Email is already registered.")
        return email

    def validate(self, attrs: dict) -> dict:
        password = attrs.get("password")
        confirm_password = attrs.get("confirm_password")
        if password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class RegistrationVerifySerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    code = serializers.CharField(min_length=4, max_length=10, trim_whitespace=False)


class LoginOTPVerifySerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    code = serializers.CharField(min_length=4, max_length=10, trim_whitespace=False)


class PasswordResetInitSerializer(serializers.Serializer):
    identifier = serializers.CharField()


class PasswordResetCompleteSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    code = serializers.CharField(min_length=4, max_length=10, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        new_password = attrs.get("new_password")
        confirm_password = attrs.get("confirm_password")
        if new_password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        try:
            validate_password(new_password)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": exc.messages}) from exc

        return attrs


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
