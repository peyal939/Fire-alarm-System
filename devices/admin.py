from django.contrib import admin

from .models import Device, Telemetry, Alert, DeviceAlarmState


class SlaveInline(admin.TabularInline):
    model = Device
    fk_name = "master"
    fields = ("hardware_identifier", "device_name", "status", "last_seen")
    readonly_fields = ("hardware_identifier", "status", "last_seen")
    extra = 0
    can_delete = False


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "hardware_identifier",
        "device_name",
        "device_role",
        "master",
        "user",
        "phone_number",
        "status",
        "last_seen",
        "registered_at",
    )
    list_filter = ("device_role", "status")
    search_fields = (
        "hardware_identifier",
        "device_name",
        "user__email",
        "phone_number",
    )
    autocomplete_fields = ("user", "master")
    inlines = [SlaveInline]


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
    list_display = (
        "device",
        "alert_type",
        "status",
        "triggered_at",
        "last_triggered_at",
        "resolved_at",
        "acknowledged_at",
    )
    list_filter = ("status", "alert_type")
    search_fields = ("device__hardware_identifier",)
    autocomplete_fields = ("device",)


@admin.register(DeviceAlarmState)
class DeviceAlarmStateAdmin(admin.ModelAdmin):
    list_display = (
        "device",
        "active_alert",
        "safe_reading_streak",
        "next_reminder_at",
        "updated_at",
    )
    search_fields = ("device__hardware_identifier",)
    autocomplete_fields = ("device", "active_alert")
