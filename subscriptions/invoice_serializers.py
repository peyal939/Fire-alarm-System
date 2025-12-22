from __future__ import annotations

from rest_framework import serializers

from .models import Invoice, InvoiceLineItem


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    """Serializer for invoice line items."""

    class Meta:
        model = InvoiceLineItem
        fields = (
            "id",
            "description",
            "quantity",
            "unit_price",
            "total",
        )


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer for invoices."""

    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    order_id = serializers.IntegerField(source="order.id", read_only=True, allow_null=True)
    subscription_charge_id = serializers.IntegerField(
        source="subscription_charge.id", read_only=True, allow_null=True
    )
    has_pdf = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            "id",
            "number",
            "user_email",
            "order_id",
            "subscription_charge_id",
            "subtotal",
            "tax",
            "total",
            "status",
            "status_display",
            "has_pdf",
            "issued_at",
            "paid_at",
            "notes",
            "line_items",
            "created_at",
            "updated_at",
        )

    def get_has_pdf(self, obj) -> bool:
        return bool(obj.pdf_file)


class InvoiceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for invoice lists."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    has_pdf = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            "id",
            "number",
            "total",
            "status",
            "status_display",
            "has_pdf",
            "issued_at",
            "paid_at",
        )

    def get_has_pdf(self, obj) -> bool:
        return bool(obj.pdf_file)


class InvoiceAdminSerializer(InvoiceSerializer):
    """Admin serializer with additional fields."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ("user_id",)
