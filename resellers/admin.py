"""Django Admin configuration for Reseller models."""
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Reseller,
    ResellerInventory,
    ResellerCustomer,
    ResellerPurchaseOrder,
    ResellerSale,
)


@admin.register(Reseller)
class ResellerAdmin(admin.ModelAdmin):
    list_display = [
        "company_name",
        "admin_user",
        "status_badge",
        "device_count",
        "customer_count",
        "available_credit",
        "created_at",
    ]
    list_filter = ["status", "country", "created_at"]
    search_fields = ["company_name", "brand_name", "admin_user__email", "contact_email"]
    readonly_fields = ["created_at", "updated_at", "created_by", "updated_by"]
    raw_id_fields = ["admin_user"]
    
    fieldsets = (
        ("Company Information", {
            "fields": (
                "admin_user",
                "company_name",
                "brand_name",
                "company_registration_number",
                "tax_id",
            )
        }),
        ("Contact", {
            "fields": (
                "contact_email",
                "contact_phone",
                "address",
                "city",
                "country",
            )
        }),
        ("Business Settings", {
            "fields": (
                "status",
                "commission_rate",
                "discount_rate",
                "credit_limit",
                "current_credit_used",
            )
        }),
        ("Branding", {
            "fields": (
                "logo_url",
                "primary_color",
                "custom_domain",
            ),
            "classes": ("collapse",),
        }),
        ("Limits", {
            "fields": (
                "max_devices",
                "max_customers",
            ),
            "classes": ("collapse",),
        }),
        ("Dates & Audit", {
            "fields": (
                "agreement_signed_at",
                "activated_at",
                "created_at",
                "created_by",
                "updated_at",
                "updated_by",
                "notes",
            ),
            "classes": ("collapse",),
        }),
    )

    def status_badge(self, obj):
        colors = {
            "pending": "#ffc107",
            "active": "#28a745",
            "suspended": "#dc3545",
            "terminated": "#6c757d",
        }
        color = colors.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"

    def device_count(self, obj):
        return obj.get_device_count()
    device_count.short_description = "Devices"

    def customer_count(self, obj):
        return obj.get_customer_count()
    customer_count.short_description = "Customers"


@admin.register(ResellerInventory)
class ResellerInventoryAdmin(admin.ModelAdmin):
    list_display = [
        "hardware_identifier",
        "reseller",
        "device_role",
        "status",
        "purchase_price",
        "sale_price",
        "profit_display",
        "created_at",
    ]
    list_filter = ["status", "device_role", "reseller"]
    search_fields = ["hardware_identifier", "reseller__company_name"]
    raw_id_fields = ["reseller", "purchase_order", "sold_to_customer"]
    readonly_fields = ["created_at", "updated_at"]

    def profit_display(self, obj):
        profit = obj.profit
        if profit is not None:
            color = "#28a745" if profit >= 0 else "#dc3545"
            return format_html(
                '<span style="color: {};">{}</span>',
                color,
                profit,
            )
        return "-"
    profit_display.short_description = "Profit"


@admin.register(ResellerCustomer)
class ResellerCustomerAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "reseller",
        "contact_name",
        "company_name",
        "is_active",
        "device_count",
        "created_at",
    ]
    list_filter = ["is_active", "reseller", "created_at"]
    search_fields = [
        "user__email",
        "contact_name",
        "company_name",
        "customer_reference",
    ]
    raw_id_fields = ["reseller", "user"]
    readonly_fields = ["created_at", "updated_at"]

    def device_count(self, obj):
        return obj.get_device_count()
    device_count.short_description = "Devices"


@admin.register(ResellerPurchaseOrder)
class ResellerPurchaseOrderAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "reseller",
        "order",
        "original_amount",
        "discount_applied",
        "final_amount",
        "is_credit_purchase",
        "created_at",
    ]
    list_filter = ["is_credit_purchase", "reseller", "created_at"]
    search_fields = ["reseller__company_name"]
    raw_id_fields = ["reseller", "order"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ResellerSale)
class ResellerSaleAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "reseller",
        "customer",
        "quantity",
        "total_amount",
        "commission_amount",
        "commission_paid",
        "created_at",
    ]
    list_filter = ["reseller", "created_at"]
    search_fields = ["reseller__company_name", "customer__contact_name"]
    raw_id_fields = ["reseller", "customer"]
    readonly_fields = ["created_at", "updated_at"]

    def commission_paid(self, obj):
        if obj.commission_paid_at:
            return format_html(
                '<span style="color: #28a745;">✓ Paid</span>'
            )
        return format_html(
            '<span style="color: #ffc107;">Pending</span>'
        )
    commission_paid.short_description = "Commission"
