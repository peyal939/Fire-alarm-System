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
            "total_amount",
            "order_status",
            "gateway_transaction_id",
            "gateway_response",
            "shipping_address",
            "ordered_at",
        )
        read_only_fields = (
            "id",
            "user",
            "total_amount",
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
        order = Order.objects.create(
            user=user,
            package=package,
            quantity=qty,
            total_amount=total,
            created_by=user,
            shipping_address=validated_data.get("shipping_address", ""),
        )
        return order

    def to_representation(self, instance):
        return OrderSerializer(instance).data
