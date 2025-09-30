from django.contrib import admin
from .models import PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "amount",
        "currency",
        "sp_order_id",
        "customer_order_id",
        "user",
        "reference",
        "created_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = ("sp_order_id", "customer_order_id", "reference")
