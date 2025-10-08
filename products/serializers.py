from __future__ import annotations

from decimal import Decimal
from rest_framework import serializers

from .models import Package, Order


class PackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Package
        fields = (
            "id",
            "name",
            "min_quantity",
            "max_quantity",
            "price_per_device",
            "mrt",
        )
        read_only_fields = ("id",)


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = (
            "id",
            "user",
            "package",
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
            "order_status",
            "gateway_transaction_id",
            "gateway_response",
            "shipping_address",
            "ordered_at",
        )
        read_only_fields = (
            "id",
            "user",
            "amount",
            "reference",
            "order_status",
            "gateway_transaction_id",
            "gateway_response",
            "ordered_at",
        )


class OrderCreateSerializer(serializers.Serializer):
    package_id = serializers.PrimaryKeyRelatedField(
        queryset=Package.objects.all(), source="package"
    )
    quantity = serializers.IntegerField(min_value=1)
    shipping_address = serializers.CharField(allow_blank=True, required=False)
    # optional customer info (reference is server-assigned)
    currency = serializers.CharField(required=False, allow_blank=True, default="BDT")
    customer_name = serializers.CharField(required=False, allow_blank=True)
    customer_address = serializers.CharField(required=False, allow_blank=True)
    customer_phone = serializers.CharField(required=False, allow_blank=True)
    customer_city = serializers.CharField(required=False, allow_blank=True)
    customer_post_code = serializers.CharField(required=False, allow_blank=True)
    customer_email = serializers.EmailField(required=False, allow_blank=True)

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
        total = package.price_per_device * Decimal(qty)
        # build kwargs for optional customer/currency fields; reference will be assigned server-side
        extra = {
            "currency": validated_data.get("currency", "BDT") or "BDT",
            "customer_name": validated_data.get("customer_name", ""),
            "customer_address": validated_data.get("customer_address", ""),
            "customer_phone": validated_data.get("customer_phone", ""),
            "customer_city": validated_data.get("customer_city", ""),
            "customer_post_code": validated_data.get("customer_post_code", ""),
            "customer_email": validated_data.get("customer_email", ""),
        }
        order = Order.objects.create(
            user=user,
            package=package,
            quantity=qty,
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
