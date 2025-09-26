from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditSoftDeleteModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by",
    )
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_deleted_by",
    )

    class Meta:
        abstract = True


class Device(AuditSoftDeleteModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    hardware_identifier = models.CharField(max_length=64, unique=True)
    device_name = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    status = models.CharField(max_length=32, blank=True)
    registered_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["hardware_identifier"]),
        ]
        # Default ordering ensures stable pagination and removes DRF warning
        ordering = ["-registered_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.hardware_identifier} ({self.device_name or 'unnamed'})"


class Telemetry(AuditSoftDeleteModel):
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="telemetry"
    )
    smoke_level = models.IntegerField()
    device_status = models.CharField(max_length=32)
    timestamp = models.DateTimeField()  # device-provided timestamp
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["device", "timestamp"]),
            models.Index(fields=["received_at"]),
        ]
        ordering = ["-timestamp"]


class Alert(AuditSoftDeleteModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="alerts")
    alert_type = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    triggered_at = models.DateTimeField(default=timezone.now, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["device", "status"]),
            models.Index(fields=["triggered_at"]),
        ]
