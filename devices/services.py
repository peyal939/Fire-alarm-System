from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Optional

import paho.mqtt.client as mqtt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import DatabaseError, models
from django.utils import timezone

from .alarm_state import record_high_smoke, record_safe_smoke, reset_state_for_alert
from .constants import (
    AlertType,
    DeviceConfigurationPublishError,
    DeviceStatus,
    MeshAlertError,
    WebSocketBroadcastError,
    normalize_device_status,
)
from .models import Alert, Device, Telemetry

logger = logging.getLogger(__name__)


def publish_device_phone_assignment(device: Device, *, phone_number: str) -> None:
    """Publish phone assignment to the IoT device via MQTT.

    Raises DeviceConfigurationPublishError when the publish attempt fails.
    """

    payload = {
        "device_id": device.hardware_identifier,
        "phoneNumber": phone_number,
        "soundOff": 0,
    }

    client: Optional[mqtt.Client] = None
    try:
        client = mqtt.Client()
        if settings.MQTT_USER:
            client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)

        client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
        client.loop_start()

        info = client.publish(
            settings.MQTT_DEVICE_REG_TOPIC,
            json.dumps(payload),
            qos=1,
            retain=False,
        )
        info.wait_for_publish(timeout=5)

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise DeviceConfigurationPublishError(
                device.hardware_identifier, f"Publish failed with code {info.rc}"
            )

        logger.info(
            "Published phone number for %s to topic %s",
            device.hardware_identifier,
            settings.MQTT_DEVICE_REG_TOPIC,
        )

    except DeviceConfigurationPublishError:
        raise
    except Exception as exc:  # pragma: no cover - network errors mocked in tests
        raise DeviceConfigurationPublishError(
            device.hardware_identifier, str(exc)
        ) from exc
    finally:
        if client is not None:
            try:
                client.loop_stop()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass


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
    """Apply mesh alarm state constrained to *online* members.

    Mesh Alert Logic:
    -----------------
    A mesh consists of a master device and all its slave devices. When any device
    in the mesh detects high smoke, all ONLINE devices in the mesh should show an alert.
    This creates a "group awareness" where users know if any device in their network
    is experiencing an issue.

    Rules:
      - Only ONLINE members (fresh last_seen) can trigger or hold a mesh alarm open.
      - When group_alarm=True:
          * Open smoke_high alerts on all online members that don't have one
          * Offline members are ignored (their old alert remains resolved)
          * This propagates the alert across the entire online mesh
      - When group_alarm=False:
          * Resolve smoke_high alerts for ALL members (online + offline)
          * This ensures the mesh clears cleanly when smoke levels normalize

    Args:
        master: The master device for the mesh (can also be passed a slave, will be resolved)
        group_alarm: True to open alerts across mesh, False to clear them

    Raises:
        Does not raise exceptions; logs errors and continues to maintain system stability
    """
    try:
        members = list(get_group_members(master))
        if not members:
            logger.warning(f"No members found for mesh with master {master.id}")
            return

        # Filter to only online devices using the is_online property
        # This prevents offline devices from keeping alerts active
        online_members = [m for m in members if getattr(m, "is_online", False)]

        if group_alarm:
            # Group alarm is active - ensure all ONLINE members have alerts
            if not online_members:
                logger.debug(
                    f"No online members in mesh {master.id}, skipping alert creation"
                )
                return

            created_alerts = []
            now = timezone.now()
            for member in online_members:
                result = record_high_smoke(device=member, observed_at=now)
                if result.created and result.alert:
                    created_alerts.append(result.alert)

            if created_alerts:
                logger.info(
                    "Created %s mesh alerts for master %s",
                    len(created_alerts),
                    master.id,
                )

                try:
                    from notifications.services import FCMService

                    for alert in created_alerts:
                        device_obj = alert.device
                        device_name = (
                            device_obj.device_name or device_obj.hardware_identifier
                        )
                        try:
                            FCMService.send_alert_notification(
                                user=device_obj.user,
                                device_name=device_name,
                                alert_type=alert.alert_type,
                                alert_id=alert.id,
                            )
                        except Exception as send_exc:
                            logger.error(
                                "Failed to send mesh notification for alert %s: %s",
                                alert.id,
                                send_exc,
                            )
                except ImportError:
                    logger.warning(
                        "Notifications service not available, skipping mesh pushes"
                    )
        else:
            # Group alarm is cleared - resolve ALL alerts (online and offline)
            # This ensures clean slate when smoke normalizes
            alerts = list(
                Alert.objects.filter(
                    device__in=[d.id for d in members],
                    alert_type=AlertType.SMOKE_HIGH,
                    status=Alert.Status.OPEN,
                )
            )

            if alerts:
                resolved_at = timezone.now()
                for alert in alerts:
                    alert.status = Alert.Status.RESOLVED
                    alert.resolved_at = resolved_at
                    alert.save(update_fields=["status", "resolved_at"])
                    reset_state_for_alert(alert)

                logger.info(
                    "Resolved %s mesh alerts for master %s",
                    len(alerts),
                    master.id,
                )

    except DatabaseError as e:
        logger.error(f"Database error applying mesh alert for master {master.id}: {e}")
    except Exception as e:
        logger.error(
            f"Unexpected error applying mesh alert for master {master.id}: {e}",
            exc_info=True,
        )


def recompute_mesh_after_change(device: Device) -> None:
    """Recompute mesh alert state after a device opens or resolves its smoke alert.

    Mesh Recomputation Logic:
    -------------------------
    When a single device's smoke alert changes (opened or resolved), we need to
    synchronize the entire mesh to ensure consistent alert state across all devices.
    This maintains the "group awareness" feature where users see if ANY device in
    their network is experiencing issues.

    Algorithm:
      1. Find the master device for this device's mesh (if device is slave, get its master)
      2. Gather all mesh members (master + all slaves)
      3. Filter to only ONLINE members (stale devices can't hold mesh alert open)
      4. Check if ANY online member has an open smoke_high alert
      5a. If YES: Ensure ALL online members have the alert (mesh propagation)
      5b. If NO: Clear ALL alerts across mesh (both online and offline)

    This approach ensures:
      - Mesh alerts don't persist after all smoke clears
      - Offline devices don't keep mesh alerts active indefinitely
      - When one online device has high smoke, all online devices show the alert

    Args:
        device: The device whose alert just changed (can be master or slave)

    Raises:
        Logs errors but doesn't propagate exceptions to maintain system stability
    """
    try:
        # Step 1: Find the master for this device's mesh
        master = get_master_for_device(device)

        # Step 2: Get all devices in the mesh (master + slaves)
        members = list(get_group_members(master))
        if not members:
            logger.warning(f"No mesh members found for device {device.id}")
            return

        # Step 3: Filter to only online devices (based on last_seen freshness)
        online_members = [m for m in members if getattr(m, "is_online", False)]

        if not online_members:
            # No online devices in mesh => clear all existing alerts
            logger.debug(
                f"No online members in mesh for device {device.id}, clearing all alerts"
            )
            Alert.objects.filter(
                device__in=[d.id for d in members],
                alert_type=AlertType.SMOKE_HIGH,
                status=Alert.Status.OPEN,
            ).update(status=Alert.Status.RESOLVED, resolved_at=timezone.now())
            return

        # Step 4: Check if any online member currently has an open alert
        open_online_ids = set(
            Alert.objects.filter(
                device_id__in=[m.id for m in online_members],
                alert_type=AlertType.SMOKE_HIGH,
                status=Alert.Status.OPEN,
            ).values_list("device_id", flat=True)
        )

        if open_online_ids:
            # Step 5a: At least one online device has high smoke
            # Propagate alert to all other online members
            to_open = [m for m in online_members if m.id not in open_online_ids]
            if to_open:
                now = timezone.now()
                created = 0
                for member in to_open:
                    result = record_high_smoke(device=member, observed_at=now)
                    if result.created:
                        created += 1

                if created:
                    logger.info(
                        "Propagated mesh alert to %s devices in mesh for device %s",
                        created,
                        device.id,
                    )
        else:
            # Step 5b: No online device has high smoke
            # Clear all alerts to ensure mesh is clean
            alerts = list(
                Alert.objects.filter(
                    device__in=[d.id for d in members],
                    alert_type=AlertType.SMOKE_HIGH,
                    status=Alert.Status.OPEN,
                )
            )

            if alerts:
                resolved_at = timezone.now()
                for alert in alerts:
                    alert.status = Alert.Status.RESOLVED
                    alert.resolved_at = resolved_at
                    alert.save(update_fields=["status", "resolved_at"])
                    reset_state_for_alert(alert)

                logger.info(
                    "Cleared %s mesh alerts for device %s",
                    len(alerts),
                    device.id,
                )

    except DatabaseError as e:
        logger.error(f"Database error recomputing mesh for device {device.id}: {e}")
        raise MeshAlertError(device.id, f"Database error: {e}")
    except Exception as e:
        logger.error(
            f"Unexpected error recomputing mesh for device {device.id}: {e}",
            exc_info=True,
        )
        # Don't raise - this is called during telemetry ingestion and shouldn't break the flow


def ingest_telemetry(
    device: Device,
    *,
    smoke_level: int,
    device_status: str,
    timestamp: dt.datetime,
) -> Optional[Telemetry]:
    """Process device telemetry and update device state, alerts, and WebSocket clients.

    This is the core telemetry ingestion function that:
    1. Persists telemetry records (only when smoke exceeds threshold)
    2. Updates device's last_seen and status fields
    3. Creates or resolves alerts based on smoke level and device status
    4. Propagates mesh alerts to related devices
    5. Broadcasts updates to WebSocket clients

    Args:
        device: The device reporting telemetry
        smoke_level: Current smoke concentration reading
        device_status: Device-reported status (e.g., "alive", "alert")
        timestamp: Device-provided timestamp for this reading

    Returns:
        Telemetry instance if smoke exceeded threshold (and record was persisted), else None

    Raises:
        Does not raise exceptions; logs errors and continues processing
    """
    threshold = getattr(settings, "SMOKE_ALERT_THRESHOLD", 100)
    telemetry: Optional[Telemetry] = None

    # Normalize device status to lowercase for consistent comparisons
    status_lower = normalize_device_status(device_status)

    # Only persist telemetry records when smoke exceeds threshold
    # This keeps the telemetry table lean by filtering out normal readings
    if smoke_level > int(threshold):
        try:
            telemetry = Telemetry.objects.create(
                device=device,
                smoke_level=smoke_level,
                device_status=status_lower,
                timestamp=timestamp,
            )
        except DatabaseError as e:
            logger.error(f"Failed to create telemetry for device {device.id}: {e}")

    # Update device's last activity timestamp and current status
    # The is_online property uses last_seen to determine if device is active
    try:
        device.status = status_lower
        device.last_seen = timezone.now()
        device.save(update_fields=["status", "last_seen"])
    except DatabaseError as e:
        logger.error(f"Failed to update device {device.id} status: {e}")

    # ========== Alert Rule 1: High Smoke Detection ==========
    # Trigger alert when smoke EXCEEDS threshold (not equals)
    # This aligns with telemetry persistence logic and UI expectations
    try:
        observed_at = timezone.now()
        if smoke_level > int(threshold):
            result = record_high_smoke(device=device, observed_at=observed_at)
            alert = result.alert
            if result.created and alert:
                logger.info(
                    "Created smoke_high alert for device %s (smoke: %s)",
                    device.id,
                    smoke_level,
                )

                # Send push notification for this single device alert
                try:
                    from notifications.services import FCMService

                    device_name = device.device_name or device.hardware_identifier
                    FCMService.send_alert_notification(
                        user=device.user,
                        device_name=device_name,
                        alert_type=AlertType.SMOKE_HIGH,
                        alert_id=alert.id,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to send notification for alert %s: %s",
                        alert.id,
                        e,
                    )

                # Propagate alert to all online members in the mesh
                # This ensures coordinated group alerting across master/slave networks
                recompute_mesh_after_change(device)
        else:
            result = record_safe_smoke(device=device, observed_at=observed_at)
            if result.resolved and result.alert:
                logger.info(
                    "Resolved smoke_high alert for device %s (smoke: %s)",
                    device.id,
                    smoke_level,
                )

                # Recompute mesh to potentially clear alerts on other devices
                recompute_mesh_after_change(device)

                # Notify WebSocket clients about the resolution so UI updates immediately
                _broadcast_alert_resolution(
                    device, smoke_level, status_lower, timestamp
                )

    except DatabaseError as e:
        logger.error(
            "Database error processing smoke alerts for device %s: %s",
            device.id,
            e,
        )
    except Exception as e:
        logger.error(
            "Unexpected error processing smoke alerts for device %s: %s",
            device.id,
            e,
            exc_info=True,
        )

    # ========== Alert Rule 2: Device Status Monitoring ==========
    # Create alert if device reports non-alive status (e.g., "alert", "error")
    try:
        if status_lower != DeviceStatus.ALIVE:
            has_open = Alert.objects.filter(
                device=device,
                alert_type=AlertType.DEVICE_STATUS,
                status=Alert.Status.OPEN,
            ).exists()
            if not has_open:
                alert = Alert.objects.create(
                    device=device,
                    alert_type=AlertType.DEVICE_STATUS,
                    status=Alert.Status.OPEN,
                )
                logger.info(
                    f"Created device_status alert for device {device.id} (status: {status_lower})"
                )

                # Send push notification for device status issue
                try:
                    from notifications.services import FCMService

                    device_name = device.device_name or device.hardware_identifier
                    FCMService.send_to_user(
                        user=device.user,
                        title="⚠️ Device Status Alert",
                        body=f"{device_name} reported status: {status_lower}",
                        data={
                            "type": "device_status",
                            "alert_id": str(alert.id),
                            "alert_type": AlertType.DEVICE_STATUS,
                            "device_name": device_name,
                            "device_status": status_lower,
                        },
                        sound="default",
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to send notification for device status alert {alert.id}: {e}"
                    )
        else:
            # Device is alive - resolve any status alerts
            qs = Alert.objects.filter(
                device=device,
                alert_type=AlertType.DEVICE_STATUS,
                status=Alert.Status.OPEN,
            )
            if qs.exists():
                qs.update(status=Alert.Status.RESOLVED, resolved_at=timezone.now())
                logger.info(f"Resolved device_status alert for device {device.id}")

    except DatabaseError as e:
        logger.error(
            f"Database error processing status alerts for device {device.id}: {e}"
        )
    except Exception as e:
        logger.error(
            f"Unexpected error processing status alerts for device {device.id}: {e}",
            exc_info=True,
        )

    return telemetry


def _broadcast_alert_resolution(
    device: Device,
    smoke_level: int,
    status: str,
    timestamp: dt.datetime,
) -> None:
    """Broadcast alert resolution to WebSocket clients.

    Helper function to notify connected clients when an alert is resolved,
    allowing real-time UI updates without polling.

    Args:
        device: The device whose alert was resolved
        smoke_level: Current smoke level
        status: Current device status
        timestamp: Timestamp of the reading
    """
    try:
        # Compute current mesh alert state across the device's group
        master_dev = get_master_for_device(device)
        member_ids = list(get_group_members(master_dev).values_list("id", flat=True))
        mesh_open = Alert.objects.filter(
            device_id__in=member_ids,
            alert_type=AlertType.SMOKE_HIGH,
            status=Alert.Status.OPEN,
        ).exists()

        # Convert timestamp to Unix epoch (integer seconds)
        ts_int = None
        try:
            ts_int = int(timestamp.timestamp())
        except (AttributeError, ValueError, OSError) as e:
            logger.warning(f"Failed to convert timestamp for device {device.id}: {e}")

        # Build WebSocket payload matching MQTT broadcast format
        payload = {
            "deviceID": device.hardware_identifier,
            "timestamp": ts_int,
            "smoke": int(smoke_level),
            "status": status,
            "mesh_alert": bool(mesh_open),
            # Legacy fields for backward compatibility
            "alert_resolved": True,
            "alert_type": AlertType.SMOKE_HIGH,
        }

        # Send to all connected WebSocket clients
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                "devices",
                {
                    "type": "device.update",
                    "device": payload,
                },
            )
            logger.debug(
                f"Broadcasted alert resolution for device {device.hardware_identifier}"
            )

    except ImportError as e:
        # Channels not configured - non-fatal in testing environments
        logger.debug(f"Channels not available for broadcast: {e}")
    except Exception as e:
        # Non-fatal: WebSocket broadcast is best-effort
        # Don't let broadcast failures break telemetry ingestion
        logger.warning(
            f"Failed to broadcast alert resolution for device {device.id}: {e}"
        )
        raise WebSocketBroadcastError(device.hardware_identifier, str(e))
