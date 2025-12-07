from django.contrib import admin, messages

from .models import Device, Telemetry, Alert, DeviceAlarmState


def _broadcast_device_removed(device):
    """Helper to clear device from cache and broadcast removal."""
    from realtime import device_cache

    device_id = getattr(device, "hardware_identifier", None)
    if not device_id:
        return

    device_cache.remove_device(device_id)

    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        if channel_layer is not None:
            payload = {"type": "device_removed", "deviceID": device_id}
            async_to_sync(channel_layer.group_send)(
                "devices",
                {
                    "type": "device.removed",
                    "payload": payload,
                    "device_id": device_id,
                },
            )
    except Exception:
        pass


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
        "deleted_at",
    )
    list_filter = ("device_role", "status", "deleted_at")
    search_fields = (
        "hardware_identifier",
        "device_name",
        "user__email",
        "phone_number",
    )
    autocomplete_fields = ("user", "master")
    inlines = [SlaveInline]
    actions = ["soft_delete_devices", "hard_delete_devices", "clear_from_cache"]

    def get_queryset(self, request):
        """Show all devices including soft-deleted ones in admin."""
        return Device.objects.all()

    @admin.action(description="Soft delete selected devices (marks as deleted)")
    def soft_delete_devices(self, request, queryset):
        """Soft delete devices and clear from cache."""
        count = 0
        for device in queryset.filter(deleted_at__isnull=True):
            device.soft_delete(acting_user=request.user)
            _broadcast_device_removed(device)
            count += 1
        self.message_user(
            request,
            f"Soft deleted {count} device(s) and cleared from cache.",
            messages.SUCCESS,
        )

    @admin.action(description="Hard delete selected devices (permanent)")
    def hard_delete_devices(self, request, queryset):
        """Hard delete devices after clearing from cache."""
        count = 0
        for device in queryset:
            _broadcast_device_removed(device)
            device.delete()
            count += 1
        self.message_user(
            request,
            f"Permanently deleted {count} device(s) and cleared from cache.",
            messages.SUCCESS,
        )

    @admin.action(description="Clear selected devices from real-time cache")
    def clear_from_cache(self, request, queryset):
        """Clear devices from cache without deleting from database."""
        from realtime import device_cache

        count = 0
        for device in queryset:
            device_id = device.hardware_identifier
            device_cache.remove_device(device_id)
            _broadcast_device_removed(device)
            count += 1
        self.message_user(
            request,
            f"Cleared {count} device(s) from real-time cache.",
            messages.SUCCESS,
        )

    def delete_model(self, request, obj):
        """Override single delete to clear cache."""
        _broadcast_device_removed(obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Override bulk delete to clear cache for each device."""
        for device in queryset:
            _broadcast_device_removed(device)
        super().delete_queryset(request, queryset)


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
