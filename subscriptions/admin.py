from django.contrib import admin

from .models import DeviceSubscription, SubscriptionCharge, Invoice, InvoiceLineItem


@admin.register(DeviceSubscription)
class DeviceSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "device",
        "status",
        "monthly_amount",
        "last_paid_through",
        "next_due_at",
    )
    list_filter = ("status",)
    search_fields = (
        "device__hardware_identifier",
        "device__device_name",
        "device__user__email",
    )
    autocomplete_fields = ("device", "originating_order")


@admin.register(SubscriptionCharge)
class SubscriptionChargeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "subscription",
        "period_start",
        "period_end",
        "amount",
        "status",
        "retry_count",
        "last_retry_at",
    )
    list_filter = ("status",)
    search_fields = ("provider_reference", "subscription__device__hardware_identifier")
    autocomplete_fields = ("subscription", "payment_transaction")
    readonly_fields = ("retry_count", "last_retry_at")


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ("total",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "user",
        "order",
        "subscription_charge",
        "total",
        "status",
        "issued_at",
        "paid_at",
    )
    list_filter = ("status", "issued_at")
    search_fields = ("number", "user__email", "order__id")
    autocomplete_fields = ("user", "order", "subscription_charge")
    readonly_fields = ("number", "issued_at", "created_at", "updated_at")
    inlines = [InvoiceLineItemInline]
    
    actions = ["generate_pdf"]
    
    @admin.action(description="Generate PDF for selected invoices")
    def generate_pdf(self, request, queryset):
        from . import invoice_utils
        count = 0
        for invoice in queryset:
            try:
                invoice_utils.save_invoice_pdf(invoice)
                count += 1
            except Exception:
                pass
        self.message_user(request, f"Generated PDF for {count} invoice(s).")

