"""Models for storing FCM device tokens and notification history."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class FCMDevice(models.Model):
    """Store Firebase Cloud Messaging device tokens for push notifications.

    Each user can have multiple devices (phone, tablet, etc.) and each device
    needs a unique FCM token to receive push notifications.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fcm_devices"
    )
    # Token can be lengthy; store as varchar(1024) without direct indexing
    # and rely on the hashed companion field for uniqueness.
    registration_token = models.CharField(
        max_length=1024,
        help_text="FCM registration token from the mobile app",
    )
    registration_token_hash = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        help_text="Hash of the FCM registration token (ensures uniqueness)",
    )
    device_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional device name for identification (e.g., 'John's iPhone')",
    )
    device_type = models.CharField(
        max_length=20,
        choices=[
            ("android", "Android"),
            ("ios", "iOS"),
            ("web", "Web"),
        ],
        default="android",
    )
    active = models.BooleanField(
        default=True, help_text="Inactive tokens will not receive notifications"
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time a notification was successfully sent to this token",
    )

    class Meta:
        indexes = [models.Index(fields=["user", "active"])]
        ordering = ["-created_at"]

    def __str__(self):
        device_info = self.device_name or f"{self.device_type} device"
        return f"{self.user.email} - {device_info}"

    def save(self, *args, **kwargs):
        import hashlib

        if self.registration_token:
            token_bytes = self.registration_token.encode("utf-8")
            self.registration_token_hash = hashlib.sha256(token_bytes).hexdigest()
        super().save(*args, **kwargs)


class NotificationLog(models.Model):
    """Log of all push notifications sent for debugging and audit purposes."""

    STATUS_CHOICES = [
        ("sent", "Sent Successfully"),
        ("failed", "Failed"),
        ("invalid_token", "Invalid Token"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_logs",
    )
    fcm_device = models.ForeignKey(
        FCMDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional data payload sent with notification",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "sent_at"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.user.email} - {self.title} ({self.status})"
