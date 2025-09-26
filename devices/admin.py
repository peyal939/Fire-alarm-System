from django.contrib import admin

from .models import Device, Telemetry, Alert


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "hardware_identifier",
        "device_name",
        "user",
        "status",
        "last_seen",
        "registered_at",
    )
    list_filter = ("status",)
    search_fields = ("hardware_identifier", "device_name", "user__email")
    autocomplete_fields = ("user",)


@admin.register(Telemetry)
class TelemetryAdmin(admin.ModelAdmin):
    list_display = (
        "device",
        "smoke_level",
        "device_status",
        "timestamp",
        "received_at",
    )
    list_filter = ("device_status",)
    search_fields = ("device__hardware_identifier",)
    autocomplete_fields = ("device",)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("device", "alert_type", "status", "triggered_at", "resolved_at")
    list_filter = ("status", "alert_type")
    search_fields = ("device__hardware_identifier",)
    autocomplete_fields = ("device",)
