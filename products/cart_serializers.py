from __future__ import annotations

from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta

from .models import Cart, CartItem, Package
from .enums import PaymentMethod


class PackageSummarySerializer(serializers.ModelSerializer):
    """Minimal package info for cart display."""

    class Meta:
        model = Package
        fields = ("id", "name", "price_per_device", "mrf", "min_quantity", "max_quantity")


class CartItemSerializer(serializers.ModelSerializer):
    """Serializer for cart items."""

    package = PackageSummarySerializer(read_only=True)
    package_id = serializers.PrimaryKeyRelatedField(
        queryset=Package.objects.filter(deleted_at__isnull=True),
        source="package",
        write_only=True,
    )
    line_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = CartItem
        fields = (
            "id",
            "package",
            "package_id",
            "quantity",
            "number_of_master_devices",
            "number_of_slave_devices",
            "line_total",
            "added_at",
            "updated_at",
        )
        read_only_fields = ("id", "line_total", "added_at", "updated_at")

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError("Quantity must be at least 1.")
        return value

    def validate(self, attrs):
        package = attrs.get("package")
        quantity = attrs.get("quantity", 1)

        if package:
            if quantity < package.min_quantity:
                raise serializers.ValidationError(
                    f"Minimum quantity for {package.name} is {package.min_quantity}."
                )
            if quantity > package.max_quantity:
                raise serializers.ValidationError(
                    f"Maximum quantity for {package.name} is {package.max_quantity}."
                )
        return attrs


class CartItemCreateSerializer(serializers.Serializer):
    """Serializer for adding items to cart."""

    package_id = serializers.PrimaryKeyRelatedField(
        queryset=Package.objects.filter(deleted_at__isnull=True),
    )
    quantity = serializers.IntegerField(min_value=1, default=1)
    number_of_master_devices = serializers.IntegerField(min_value=0, default=1)
    number_of_slave_devices = serializers.IntegerField(min_value=0, default=0)

    def validate(self, attrs):
        package = attrs["package_id"]
        quantity = attrs.get("quantity", 1)

        if quantity < package.min_quantity:
            raise serializers.ValidationError(
                f"Minimum quantity for {package.name} is {package.min_quantity}."
            )
        if quantity > package.max_quantity:
            raise serializers.ValidationError(
                f"Maximum quantity for {package.name} is {package.max_quantity}."
            )
        return attrs


class CartItemUpdateSerializer(serializers.Serializer):
    """Serializer for updating cart item quantity."""

    quantity = serializers.IntegerField(min_value=1)
    number_of_master_devices = serializers.IntegerField(min_value=0, required=False)
    number_of_slave_devices = serializers.IntegerField(min_value=0, required=False)


class CartItemBulkCreateSerializer(serializers.Serializer):
    """Serializer for bulk adding items to cart."""

    items = serializers.ListField(
        child=CartItemCreateSerializer(),
        min_length=1,
        max_length=50,
        help_text="List of items to add to cart (max 50 items)",
    )

    def validate_items(self, value):
        # Check for duplicate package_ids in the request
        package_ids = [item["package_id"].id for item in value]
        if len(package_ids) != len(set(package_ids)):
            raise serializers.ValidationError(
                "Duplicate package_id found in items. Each package can only appear once."
            )
        return value


class CartSerializer(serializers.ModelSerializer):
    """Serializer for the shopping cart."""

    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Cart
        fields = (
            "id",
            "items",
            "total",
            "item_count",
            "expires_at",
            "is_expired",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_total(self, obj) -> str:
        return str(obj.get_total())

    def get_item_count(self, obj) -> int:
        return obj.items.count()


class CartCheckoutSerializer(serializers.Serializer):
    """Serializer for cart checkout - converts cart to order(s)."""

    shipping_address = serializers.CharField(required=False, allow_blank=True)
    customer_name = serializers.CharField(required=False, allow_blank=True)
    customer_address = serializers.CharField(required=False, allow_blank=True)
    customer_phone = serializers.CharField(required=False, allow_blank=True)
    customer_city = serializers.CharField(required=False, allow_blank=True)
    customer_post_code = serializers.CharField(required=False, allow_blank=True)
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    currency = serializers.CharField(required=False, default="BDT")
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        default=PaymentMethod.ONLINE,
    )

    def validate_currency(self, value):
        v = (value or "BDT").strip().upper()
        if len(v) > 8:
            raise serializers.ValidationError("Currency must be at most 8 characters.")
        return v or "BDT"
