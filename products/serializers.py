from __future__ import annotations

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from .models import Package, Order, OrderFulfillment
from .enums import PaymentMethod
from .services import calculate_order_total


class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = (
            "id",
            "name",
            "min_quantity",
            "max_quantity",
            "price_per_device",
            "mrf",
            "description",
        )
        read_only_fields = ("id",)


class PackageSummarySerializer(serializers.ModelSerializer):
    """Minimal package info for order display (with pricing)."""
    class Meta:
        model = Package
        fields = ("id", "name", "price_per_device", "mrf", "min_quantity", "max_quantity")


class OrderSerializer(serializers.ModelSerializer):
    # Additional fields for admin panel display
    user_email = serializers.SerializerMethodField()
    user_phone = serializers.SerializerMethodField()
    package_name = serializers.SerializerMethodField()
    total_amount = serializers.DecimalField(source='amount', max_digits=10, decimal_places=2, read_only=True)
    status = serializers.CharField(source='order_status', read_only=True)
    created_at = serializers.DateTimeField(source='ordered_at', read_only=True)
    package = PackageSummarySerializer(read_only=True)
    
    class Meta:
        model = Order
        fields = (
            "id",
            "user",
            "package",
            "number_of_master_devices",
            "number_of_slave_devices",
            "quantity",
            "amount",
            "currency",
            "reference",
            "customer_name",
            "customer_address",
            "customer_phone",
            "customer_city",
            "customer_post_code",
            "customer_email",
            "payment_method",
            "order_status",
            "gateway_transaction_id",
            "gateway_response",
            "shipping_address",
            "ordered_at",
            "assigned_devices",
            # Additional computed fields for admin panel
            "user_email",
            "user_phone",
            "package_name",
            "total_amount",
            "status",
            "created_at",
        )
        read_only_fields = (
            "id",
            "user",
            "amount",
            "reference",
            "payment_method",
            "order_status",
            "gateway_transaction_id",
            "gateway_response",
            "ordered_at",
        )
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_user_email(self, obj) -> str | None:
        if obj.user:
            return obj.user.email or obj.user.get_username()
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_user_phone(self, obj) -> str | None:
        # Try customer_phone first, then user's phone
        if obj.customer_phone:
            return obj.customer_phone
        if obj.user and hasattr(obj.user, 'phone'):
            return obj.user.phone
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_package_name(self, obj) -> str | None:
        if obj.package:
            return obj.package.name
        return None


class OrderCreateSerializer(serializers.Serializer):
    package_id = serializers.PrimaryKeyRelatedField(
        queryset=Package.objects.all(), source="package"
    )
    quantity = serializers.IntegerField(min_value=1)
    number_of_master_devices = serializers.IntegerField(min_value=0, default=1)
    number_of_slave_devices = serializers.IntegerField(min_value=0, default=1)
    shipping_address = serializers.CharField(allow_blank=True, required=False)
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        default=PaymentMethod.ONLINE,
    )
    # optional customer info (reference is server-assigned)
    currency = serializers.CharField(required=False, allow_blank=True, default="BDT")
    customer_name = serializers.CharField(required=False, allow_blank=True)
    customer_address = serializers.CharField(required=False, allow_blank=True)
    customer_phone = serializers.CharField(required=False, allow_blank=True)
    customer_city = serializers.CharField(required=False, allow_blank=True)
    customer_post_code = serializers.CharField(required=False, allow_blank=True)
    customer_email = serializers.EmailField(required=False, allow_blank=True)

    def validate_currency(self, value: str) -> str:
        # Normalize and enforce DB max length for currency to prevent 500s
        v = (value or "BDT").strip().upper()
        max_len = Order._meta.get_field("currency").max_length
        if len(v) > max_len:
            raise serializers.ValidationError(
                f"Currency must be at most {max_len} characters."
            )
        return v or "BDT"

    def validate(self, attrs):
        package: Package = attrs["package"]
        qty = attrs["quantity"]
        if qty < package.min_quantity:
            raise serializers.ValidationError(
                f"Minimum quantity for package {package.name} is {package.min_quantity}"
            )
        if qty > package.max_quantity:
            raise serializers.ValidationError(
                f"Maximum quantity for package {package.name} is {package.max_quantity}"
            )
        return attrs

    def create(self, validated_data):
        package: Package = validated_data["package"]
        qty = validated_data["quantity"]
        user = self.context["request"].user
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required")
        if user.is_superuser or getattr(user, "role", "") == "superadmin":
            raise serializers.ValidationError(
                "Admin or super admin can't create any order. Only User can create order."
            )
        total = calculate_order_total(package, qty)
        master_devices = validated_data.get("number_of_master_devices", 1)
        slave_devices = validated_data.get("number_of_slave_devices", 1)
        payment_method = validated_data.get("payment_method", PaymentMethod.ONLINE)
        # build kwargs for optional customer/currency fields; reference will be assigned server-side
        extra = {
            "currency": validated_data.get("currency", "BDT") or "BDT",
            "customer_name": validated_data.get("customer_name", ""),
            "customer_address": validated_data.get("customer_address", ""),
            "customer_phone": validated_data.get("customer_phone", ""),
            "customer_city": validated_data.get("customer_city", ""),
            "customer_post_code": validated_data.get("customer_post_code", ""),
            "customer_email": validated_data.get("customer_email", ""),
            "payment_method": payment_method,
        }
        order = Order.objects.create(
            user=user,
            package=package,
            quantity=qty,
            number_of_master_devices=master_devices,
            number_of_slave_devices=slave_devices,
            amount=total,
            created_by=user,
            shipping_address=validated_data.get("shipping_address", ""),
            **extra,
        )
        # assign server-side reference to the auto-incremented id (hide from client input)
        order.reference = str(order.id)
        order.save(update_fields=["reference"])
        return order

    def to_representation(self, instance):
        return OrderSerializer(instance).data


class OrderPaymentInitSerializer(serializers.Serializer):
    """Serializer for initializing order payment from the client.

    This keeps the schema explicit for OrderPaymentInitView without
    changing its runtime behavior.
    """

    order_id = serializers.IntegerField(help_text="ID of the order to initiate payment for")


class OrderFulfillmentSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(read_only=True)
    user_email = serializers.EmailField(source="order.user.email", read_only=True)

    class Meta:
        model = OrderFulfillment
        fields = (
            "id",
            "order_id",
            "user_email",
            "hardware_identifier",
            "device_role",
            "master_hardware_identifier",
            "is_claimed",
            "created_at",
        )
        read_only_fields = fields
