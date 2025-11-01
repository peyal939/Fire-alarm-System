from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
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

    def soft_delete(self, *, acting_user=None, using=None, timestamp=None):
        """Mark the record as deleted without triggering model validation."""
        if self.pk is None:
            raise ValueError("Cannot soft delete an unsaved instance")

        ts = timestamp or timezone.now()
        deleted_by_id = getattr(acting_user, "pk", None)

        manager = self.__class__._default_manager
        if using:
            manager = manager.using(using)
        elif self._state.db:
            manager = manager.using(self._state.db)

        manager.filter(pk=self.pk).update(
            deleted_at=ts,
            deleted_by_id=deleted_by_id,
        )

        self.deleted_at = ts
        self.deleted_by = acting_user
        return ts


class Device(AuditSoftDeleteModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    hardware_identifier = models.CharField(max_length=64, unique=True)
    device_name = models.CharField(max_length=255, blank=True)

    class DeviceRole(models.TextChoices):
        MASTER = "master", "Master"
        SLAVE = "slave", "Slave"

    device_role = models.CharField(
        max_length=10,
        choices=DeviceRole.choices,
        default=DeviceRole.MASTER,
        db_index=True,
    )
    master = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="slaves",
        on_delete=models.PROTECT,
    )
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    phone_number = models.CharField(max_length=16, null=True, blank=True)
    phone_number_updated_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, blank=True)
    registered_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)

    # --- Runtime / derived properties (not stored) ---------------------------------
    @property
    def is_online(self) -> bool:
        """Return True if the device has been seen within the freshness window.

        The freshness window is configured via settings.DEVICE_ONLINE_FRESHNESS_SECONDS
        (default 180 seconds). This avoids relying on the persisted textual `status`
        field which comes from the hardware payload. A slave that stops sending data
        will naturally become offline once its own last_seen grows stale (a master
        transmitting does NOT update its slaves' last_seen unless a slave section is
        actually present in the composite payload).
        """
        if not self.last_seen:
            return False
        from django.conf import settings as _s  # local import to avoid circular
        from django.utils import timezone as _tz

        try:
            window = int(getattr(_s, "DEVICE_ONLINE_FRESHNESS_SECONDS", 180))
        except Exception:
            window = 180
        return self.last_seen >= _tz.now() - _tz.timedelta(seconds=window)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["hardware_identifier"]),
            models.Index(fields=["device_role"]),
            models.Index(fields=["master"]),
        ]
        # Default ordering surfaces most recently active devices first while preserving stability
        ordering = ["-last_seen", "-registered_at"]
        constraints = [
            # If role is master, master FK must be NULL
            models.CheckConstraint(
                name="device_master_null_if_role_master",
                check=Q(device_role="master", master__isnull=True)
                | ~Q(device_role="master"),
            ),
            # If role is slave, master FK must be NOT NULL
            models.CheckConstraint(
                name="device_master_not_null_if_role_slave",
                check=Q(device_role="slave", master__isnull=False)
                | ~Q(device_role="slave"),
            ),
            # Note: self-reference prevention is enforced in clean(),
            # since some MySQL versions disallow CHECKs on auto-increment columns.
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.hardware_identifier} ({self.device_name or 'unnamed'})"

    def clean(self):  # pragma: no cover - validated by tests/admin
        # Normalize role
        role = self.device_role or Device.DeviceRole.MASTER
        # Self-reference check (only when pk known)
        if self.pk and self.master_id and self.master_id == self.pk:
            raise ValidationError({"master": "Device cannot be its own master."})
        # Role + master rules
        if role == Device.DeviceRole.MASTER:
            if self.master_id is not None:
                raise ValidationError(
                    {"master": "Master devices cannot have a master."}
                )
        elif role == Device.DeviceRole.SLAVE:
            if not self.master_id:
                raise ValidationError(
                    {"master": "Slave devices must reference a master."}
                )
            if (
                self.master
                and getattr(self.master, "device_role", None)
                != Device.DeviceRole.MASTER
            ):
                raise ValidationError(
                    {"master": "Selected master must be a master device."}
                )
            # Enforce same owner
            if self.master and self.master.user_id != self.user_id:
                # Allow superadmins (or superusers) who are creating/updating the record
                # to attach a slave to a master owned by another user. We check
                # `created_by` because model.clean() doesn't receive request context;
                # the view should set created_by=request.user when creating programmatically.
                creator = getattr(self, "created_by", None)
                if not (
                    creator
                    and (
                        getattr(creator, "role", None) == "superadmin"
                        or getattr(creator, "is_superuser", False)
                    )
                ):
                    raise ValidationError(
                        {"user": "Slave must belong to the same user as its master."}
                    )
        else:
            raise ValidationError({"device_role": "Invalid device role."})

    def save(self, *args, **kwargs):
        validate = kwargs.pop("validate", None)
        update_fields = kwargs.get("update_fields")

        if validate is None:
            if update_fields:
                safe_fields = {
                    "status",
                    "last_seen",
                    "phone_number",
                    "phone_number_updated_at",
                    "deleted_at",
                    "deleted_by",
                }
                try:
                    fields_set = {str(field) for field in update_fields}
                except TypeError:
                    fields_set = {str(update_fields)}
                validate = not fields_set.issubset(safe_fields)
            else:
                validate = True

        if validate:
            # Ensure validations apply across all save paths (including programmatic saves)
            self.full_clean()
        return super().save(*args, **kwargs)


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
        # Ensure stable pagination ordering
        ordering = ["-triggered_at"]
