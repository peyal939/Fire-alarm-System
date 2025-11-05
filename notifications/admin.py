"""Admin configuration for notifications app."""

from django.contrib import admin
from .models import FCMDevice, NotificationLog


@admin.register(FCMDevice)
class FCMDeviceAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "device_name",
        "device_type",
        "active",
        "created_at",
        "last_used_at",
    ]
    list_filter = ["active", "device_type", "created_at"]
    search_fields = ["user__email", "device_name", "registration_token"]
    readonly_fields = [
        "created_at",
        "updated_at",
        "last_used_at",
        "registration_token_hash",
    ]

    fieldsets = (
        (
            "Device Information",
            {
                "fields": (
                    "user",
                    "registration_token",
                    "registration_token_hash",
                    "device_name",
                    "device_type",
                )
            },
        ),
        ("Status", {"fields": ("active",)}),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at", "last_used_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "title", "status", "sent_at"]
    list_filter = ["status", "sent_at"]
    search_fields = ["user__email", "title", "body"]
    readonly_fields = [
        "user",
        "fcm_device",
        "title",
        "body",
        "data",
        "status",
        "error_message",
        "sent_at",
    ]

    def has_add_permission(self, request):
        # Logs are created automatically, not manually
        return False

    def has_change_permission(self, request, obj=None):
        # Logs should not be edited
        return False
