from django.contrib import admin
from .models import Package, Order


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "min_quantity", "max_quantity", "price_per_device", "mrt")
    search_fields = ("name",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "package",
        "quantity",
        "total_amount",
        "order_status",
        "ordered_at",
    )
    list_filter = ("order_status", "package")
    search_fields = ("id", "gateway_transaction_id")
