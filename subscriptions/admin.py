from django.contrib import admin

from .models import DeviceSubscription, SubscriptionCharge


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
    )
    list_filter = ("status",)
    search_fields = ("provider_reference", "subscription__device__hardware_identifier")
    autocomplete_fields = ("subscription", "payment_transaction")
