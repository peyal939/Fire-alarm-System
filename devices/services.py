from __future__ import annotations

import datetime as dt
from typing import Optional

from django.utils import timezone
from django.conf import settings

from .models import Device, Telemetry, Alert


def ingest_by_hardware_identifier(
    hardware_identifier: str,
    *,
    smoke_level: int,
    device_status: str,
    timestamp: dt.datetime,
) -> bool:
    """Ingest telemetry for a device by its hardware identifier.

    Returns True if ingested (device exists and not deleted), False otherwise.
    """
    device = (
        Device.objects.filter(
            hardware_identifier=hardware_identifier, deleted_at__isnull=True
        )
        .select_related("user")
        .first()
    )
    if not device:
        return False
    ingest_telemetry(
        device,
        smoke_level=smoke_level,
        device_status=device_status,
        timestamp=timestamp,
    )
    return True


def ingest_telemetry(
    device: Device,
    *,
    smoke_level: int,
    device_status: str,
    timestamp: dt.datetime,
) -> Optional[Telemetry]:
    """Update device status/last_seen and evaluate alerts.

    Persist a Telemetry row only when smoke_level exceeds the configured threshold.
    Returns the Telemetry instance if created, else None.
    """
    threshold = getattr(settings, "SMOKE_ALERT_THRESHOLD", 100)
    telemetry: Optional[Telemetry] = None
    # Normalize status for logic checks while preserving original in storage
    status_raw = device_status or ""
    status_norm = str(status_raw).strip()
    status_lower = status_norm.lower()
    if smoke_level > int(threshold):
        telemetry = Telemetry.objects.create(
            device=device,
            smoke_level=smoke_level,
            device_status=status_norm,
            timestamp=timestamp,
        )

    # Update device status/last_seen
    device.status = status_norm
    device.last_seen = timezone.now()
    device.save(update_fields=["status", "last_seen"])

    # Rule 1: high smoke (trigger only when strictly above threshold, aligns with UI and telemetry persistence)
    if smoke_level > int(threshold):
        has_open = Alert.objects.filter(
            device=device, alert_type="smoke_high", status=Alert.Status.OPEN
        ).exists()
        if not has_open:
            Alert.objects.create(
                device=device, alert_type="smoke_high", status=Alert.Status.OPEN
            )
    else:
        qs = Alert.objects.filter(
            device=device, alert_type="smoke_high", status=Alert.Status.OPEN
        )
        if qs.exists():
            qs.update(status=Alert.Status.RESOLVED, resolved_at=timezone.now())

    # Rule 2: device status not alive
    if status_lower != "alive":
        has_open = Alert.objects.filter(
            device=device, alert_type="device_status", status=Alert.Status.OPEN
        ).exists()
        if not has_open:
            Alert.objects.create(
                device=device, alert_type="device_status", status=Alert.Status.OPEN
            )
    else:
        qs = Alert.objects.filter(
            device=device, alert_type="device_status", status=Alert.Status.OPEN
        )
        if qs.exists():
            qs.update(status=Alert.Status.RESOLVED, resolved_at=timezone.now())

    return telemetry
