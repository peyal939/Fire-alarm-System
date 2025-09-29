from __future__ import annotations

import datetime as dt
from typing import Optional

from django.utils import timezone
from django.conf import settings
from django.db import models

from .models import Device, Telemetry, Alert
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


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


def get_master_for_device(device: Device) -> Device:
    """Return the master device for a given device (itself if it's a master)."""
    if (
        getattr(device, "device_role", None) == Device.DeviceRole.SLAVE
        and device.master_id
    ):
        return device.master  # type: ignore[return-value]
    return device


def get_group_members(master: Device):
    """Return a queryset of all members in the master's mesh (master + slaves)."""
    # Ensure we have a master instance
    m = master
    if (
        getattr(master, "device_role", None) == Device.DeviceRole.SLAVE
        and master.master_id
    ):
        m = master.master  # type: ignore[assignment]
    # master + slaves, excluding soft-deleted
    return (
        Device.objects.filter(deleted_at__isnull=True)
        .filter(models.Q(id=m.id) | models.Q(master_id=m.id))
        .select_related("user", "master")
    )


def apply_mesh_alert(master: Device, *, group_alarm: bool) -> None:
    """Ensure per-device Alerts reflect group alarm for all members.

    - If group_alarm is True: open smoke_high Alert for every member (create if missing)
    - If False: resolve any open smoke_high Alert for every member
    """
    members = list(get_group_members(master))
    if not members:
        return
    if group_alarm:
        # Open alert for each member if not already open
        open_map = {
            d.id: Alert.objects.filter(
                device=d, alert_type="smoke_high", status=Alert.Status.OPEN
            ).exists()
            for d in members
        }
        to_create = [d for d in members if not open_map.get(d.id)]
        Alert.objects.bulk_create(
            [
                Alert(device=d, alert_type="smoke_high", status=Alert.Status.OPEN)
                for d in to_create
            ]
        )
    else:
        # Resolve all open alerts for members
        Alert.objects.filter(
            device__in=[d.id for d in members],
            alert_type="smoke_high",
            status=Alert.Status.OPEN,
        ).update(status=Alert.Status.RESOLVED, resolved_at=timezone.now())


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
    # Normalize status for logic checks and storage
    status_raw = device_status or ""
    status_norm = str(status_raw).strip()
    status_lower = status_norm.lower()
    if smoke_level > int(threshold):
        telemetry = Telemetry.objects.create(
            device=device,
            smoke_level=smoke_level,
            device_status=status_lower,
            timestamp=timestamp,
        )

    # Update device status/last_seen (online/offline is derived by UI/API using last_seen freshness + status=='alive')
    device.status = status_lower
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
            # Notify websocket clients with an up-to-date device snapshot so UI can refresh smoke/status immediately
            try:
                # Compute mesh_alert across the device's group (master + slaves)
                master_dev = get_master_for_device(device)
                member_ids = list(
                    get_group_members(master_dev).values_list("id", flat=True)
                )
                mesh_open = Alert.objects.filter(
                    device_id__in=member_ids,
                    alert_type="smoke_high",
                    status=Alert.Status.OPEN,
                ).exists()

                # Build minimal but complete payload similar to MQTT broadcast
                ts_int = None
                try:
                    ts_int = int(timestamp.timestamp())
                except Exception:
                    ts_int = None

                payload = {
                    "deviceID": device.hardware_identifier,
                    "timestamp": ts_int,
                    "smoke": int(smoke_level),
                    "status": status_lower,
                    "mesh_alert": bool(mesh_open),
                    # Keep legacy flags for consumers relying on them
                    "alert_resolved": True,
                    "alert_type": "smoke_high",
                }

                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "devices",
                    {
                        "type": "device.update",
                        "device": payload,
                    },
                )
            except Exception:
                # Non-fatal: best-effort notify
                pass

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
