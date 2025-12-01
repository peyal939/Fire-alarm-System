"""MQTT telemetry ingestion and real-time WebSocket broadcasting.

This module handles incoming MQTT messages from IoT devices, processes telemetry data,
and broadcasts updates to connected WebSocket clients for real-time dashboard updates.

Supported Payload Formats:
    1. Legacy single-device format
    2. Composite master/slave format for mesh networks
"""

import json
import logging
import threading
import datetime as dt
import time
from typing import Optional, Tuple, List, Dict, Any
from decimal import Decimal

import paho.mqtt.client as mqtt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models

from django.conf import settings
from django.utils import timezone
from django.db import close_old_connections
from django.db.utils import InterfaceError, OperationalError

from devices.enums import AlertStatus
from devices.models import Device, Telemetry, Alert

from devices import services
from devices.constants import (
    AlertType,
    DeviceStatus,
    MQTTPayloadKeys,
    InvalidTelemetryPayloadError,
    UnregisteredDeviceError,
    MQTTProcessingError,
)
from . import device_cache

logger = logging.getLogger(__name__)
_thread_started = False

# MQTT connection status tracking for health checks
_mqtt_status = {
    "connected": False,
    "last_message_time": None,
    "connection_time": None,
    "error": None,
    "broker": None,
    "port": None,
}


def get_mqtt_status():
    """Return current MQTT connection status for health checks.

    Returns:
        dict: Status information including connection state, timestamps, and errors
    """
    return _mqtt_status.copy()


def _fmt12(dtobj: dt.datetime) -> str:
    s = dtobj.strftime("%d %b %Y, %I:%M:%S %p")
    return s.replace("AM", "am").replace("PM", "pm")


def _to_int(value, default=None) -> Optional[int]:
    """Safely convert value to integer with fallback.

    Args:
        value: Value to convert (string, int, or other)
        default: Value to return if conversion fails

    Returns:
        Integer value or default
    """
    try:
        if isinstance(value, str):
            value = value.strip()
        return int(value)
    except (ValueError, TypeError, AttributeError):
        return default


def _to_ts_dt(ts_val) -> Tuple[Optional[int], dt.datetime]:
    """Convert timestamp value to integer and datetime objects.

    Args:
        ts_val: Unix timestamp (int or string)

    Returns:
        Tuple of (timestamp_int, datetime_obj). If conversion fails,
        returns (None, current_time) or (ts_int, current_time)
    """
    tz = timezone.get_current_timezone()
    ts_int = _to_int(ts_val)
    if ts_int is None:
        return None, timezone.now()
    try:
        return ts_int, dt.datetime.fromtimestamp(ts_int, tz=tz)
    except (ValueError, OSError, OverflowError) as e:
        logger.warning(f"Invalid timestamp {ts_int}: {e}")
        return ts_int, timezone.now()


def _compute_mesh_alert(device_obj: Device) -> bool:
    """Check if any device in the mesh network has an active smoke alert.

    A mesh network consists of a master device and all its slave devices.
    This function determines if ANY device in that network currently has
    an open smoke_high alert, which is used for the "mesh_alert" flag
    in WebSocket broadcasts.

    Args:
        device_obj: Any device in the mesh (master or slave)

    Returns:
        True if any device in the mesh has an open smoke_high alert, False otherwise

    Note:
        For slave devices, this looks up their master first.
        If no master is found (orphaned slave), treats device as its own master.
    """
    try:
        from devices.models import Alert

        # Identify the master device for this mesh
        # If device is already a master, use it directly
        # If device is a slave, use its master (or itself if master is None)
        master = (
            device_obj
            if device_obj.device_role == Device.DeviceRole.MASTER
            else (device_obj.master or device_obj)
        )

        # Get all member device IDs in this mesh (master + all slaves)
        member_ids = list(
            Device.objects.filter(deleted_at__isnull=True)
            .filter(models.Q(id=master.id) | models.Q(master_id=master.id))
            .values_list("id", flat=True)
        )

        if not member_ids:
            logger.debug(f"No mesh members found for device {device_obj.id}")
            return False

        # Check if any member has an open smoke_high alert
        has_alert = Alert.objects.filter(
            device_id__in=member_ids,
            alert_type=AlertType.SMOKE_HIGH,
            status=AlertStatus.OPEN,
        ).exists()

        return has_alert

    except Exception as e:
        logger.error(
            f"Error computing mesh alert for device {device_obj.id}: {e}", exc_info=True
        )
        return False


def _broadcast_device_update(
    device_obj: Device,
    *,
    device_id: str,
    ts_int: Optional[int],
    ts_dt: dt.datetime,
    smoke_val: int,
    status_str: str,
) -> None:
    """Broadcast device telemetry update to WebSocket clients and update in-memory cache.

    This function constructs a complete device state payload including:
    - Current readings (smoke, status)
    - Timestamps (Unix int and human-readable ISO)
    - Location coordinates (if available)
    - Online status (derived from last_seen freshness)
    - Mesh alert status (group-wide alert state)

    The payload is:
    1. Persisted to the shared device cache (Redis when available, in-memory fallback)
    2. Broadcast to all connected WebSocket clients via Channels layer

    Args:
        device_obj: Device model instance
        device_id: Hardware identifier for the device
        ts_int: Unix timestamp (seconds since epoch) or None
        ts_dt: Datetime object for the reading
        smoke_val: Smoke level reading
        status_str: Device status string (e.g., "alive", "alert")

    Raises:
        Does not raise; logs errors and continues
    """
    # Extract persisted GPS coordinates if available
    pos = None
    try:
        if device_obj.latitude is not None and device_obj.longitude is not None:
            pos = {
                "latitude": float(device_obj.latitude),
                "longitude": float(device_obj.longitude),
            }
    except (TypeError, ValueError, Decimal.InvalidOperation) as e:
        logger.warning(f"Invalid coordinates for device {device_id}: {e}")

    # Format timestamps in local timezone for human readability
    timestamp_iso = None
    received_at_iso = None
    try:
        tz = timezone.get_current_timezone()
        ts_dt_local = ts_dt.astimezone(tz)
        rec_local = timezone.now().astimezone(tz)
        timestamp_iso = _fmt12(ts_dt_local)
        received_at_iso = _fmt12(rec_local)
    except (AttributeError, ValueError, OSError) as e:
        logger.warning(f"Timestamp formatting failed for device {device_id}: {e}")

    # Add mesh alert flag to show group-wide alert state
    mesh_alert = False
    try:
        mesh_alert = bool(_compute_mesh_alert(device_obj))
    except Exception as e:
        logger.error(f"Failed to compute mesh alert for device {device_id}: {e}")

    owner_id = getattr(device_obj, "user_id", None)
    owner_email = None
    try:
        owner_email = getattr(getattr(device_obj, "user", None), "email", None)
    except Exception:
        owner_email = None

    # Build the complete device state payload
    device_payload = {
        MQTTPayloadKeys.DEVICE_ID: device_id,
        MQTTPayloadKeys.TIMESTAMP: ts_int,
        "timestamp_iso": timestamp_iso,
        "received_at_iso": received_at_iso,
        MQTTPayloadKeys.SMOKE: smoke_val,
        MQTTPayloadKeys.STATUS: status_str,
        # Derive online status from last_seen freshness (defined in Device.is_online property)
        # This allows frontend to show real-time offline transitions without API polling
        "online": bool(getattr(device_obj, "is_online", False)),
        "mesh_alert": mesh_alert,
        "owner_id": owner_id,
    }

    if owner_email:
        device_payload["owner_email"] = owner_email

    # Include GPS coordinates if available
    if pos is not None:
        device_payload["latitude"] = pos["latitude"]
        device_payload["longitude"] = pos["longitude"]

    # Update in-memory cache for snapshot delivery to new WebSocket connections
    device_cache.set_device_state(device_id, device_payload)

    # Always broadcast MQTT messages for real-time updates (removed throttling)
    # The channel capacity increase (1000) and message expiry (60s) handle burst traffic
    try:
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                "devices", {"type": "device.update", "device": device_payload}
            )
            logger.debug(f"Broadcasted update for device {device_id}")
    except ImportError:
        # Channels not configured - expected in test environments
        logger.debug("Channels not available for broadcast")
    except Exception as e:
        # Non-fatal: WebSocket broadcast failures shouldn't break telemetry ingestion
        # This includes channel overflow - log but don't crash
        logger.warning(f"Failed to broadcast update for device {device_id}: {e}")


def broadcast_device_removed(device_obj: Device) -> None:
    """Remove device from cache and broadcast deletion to WebSocket clients."""

    device_id = getattr(device_obj, "hardware_identifier", None)
    if not device_id:
        return

    device_cache.remove_device(device_id)

    try:
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
    except Exception as exc:  # pragma: no cover - best-effort broadcast
        logger.warning(
            "Failed to broadcast removal for device %s: %s",
            device_id,
            exc,
        )


def process_payload(payload: dict) -> None:
    """Process an already-parsed MQTT payload dict.

    Supports both legacy single-device and composite master/slave payloads.
    Safe to call from tests.
    """
    # --- MongoDB Historical Data Recording (Sidecar) ---
    try:
        from utils.mongo_client import mongo_client

        # We clone the payload to avoid side effects if the main logic modifies it
        # We also add a server-side timestamp for strict ordering
        mongo_doc = payload.copy() if isinstance(payload, dict) else {"raw": payload}

        # Ensure there is a timestamp field (required for Time Series)
        if "timestamp" not in mongo_doc or not mongo_doc["timestamp"]:
            mongo_doc["timestamp"] = timezone.now()
        else:
            # Convert Unix timestamp to datetime if needed, because Mongo Time Series
            # requires the timeField to be a BSON Date (datetime object)
            ts_val = mongo_doc["timestamp"]
            if isinstance(ts_val, (int, float, str)):
                _, ts_dt = _to_ts_dt(ts_val)
                mongo_doc["timestamp"] = ts_dt

        # Add metadata
        mongo_doc["metadata"] = {
            "ingested_at": timezone.now(),
            "source": "mqtt_process_payload",
        }

        # Fire-and-forget insert
        mongo_client.insert_one(mongo_doc)
    except Exception as e:
        # NEVER break the main loop for historical data errors
        logger.error(f"Failed to record to MongoDB: {e}")
    # ---------------------------------------------------

    try:
        # Ensure background thread holds a fresh DB connection
        close_old_connections()
    except Exception:
        pass
    # Composite payload from master? Expect an array at 'slaves'
    slaves_part = payload.get("slaves")
    if isinstance(slaves_part, list):
        master_id = str(
            payload.get("masterDeviceID")
            or payload.get("masterID")
            or payload.get("deviceID")
            or ""
        ).strip()
        if not master_id:
            logging.info(
                "Composite payload missing masterDeviceID/masterID/deviceID; ignoring"
            )
            return

        # Lookup master device (must be registered & not deleted)
        master_obj = (
            Device.objects.filter(
                hardware_identifier=master_id, deleted_at__isnull=True
            )
            .select_related("user")
            .first()
        )
        if not master_obj:
            logging.info(
                f"Ignoring composite telemetry from unknown master '{master_id}'"
            )
            return

        # Master level fields (status optional -> default alive; smoke optional -> default 0)
        m_status = payload.get("status")
        m_status = (
            str(m_status).strip()
            if isinstance(m_status, str)
            else (m_status or "alive")
        )
        m_smoke = _to_int(payload.get("smoke"), default=0)
        m_ts_int, m_ts_dt = _to_ts_dt(payload.get("timestamp"))

        # Ingest master now; defer broadcast until after mesh alert is applied
        services.ingest_telemetry(
            master_obj,
            smoke_level=m_smoke or 0,
            device_status=m_status or "alive",
            timestamp=m_ts_dt,
        )

        # Process slaves, enforcing preregistration under this master
        # Track group alarm across all members
        threshold = int(getattr(settings, "SMOKE_ALERT_THRESHOLD", 50))
        group_alarm = (m_smoke or 0) > threshold
        # Use canonical device ID from database for consistent WebSocket broadcasting
        master_canonical_id = master_obj.hardware_identifier
        devices_for_broadcast = [
            (
                master_obj,
                master_canonical_id,
                m_ts_int,
                m_ts_dt,
                (m_smoke or 0),
                (m_status or "alive"),
            )
        ]

        for idx, sd in enumerate(slaves_part):
            sid = str(sd.get("deviceID") or sd.get("id") or "").strip()
            if not sid:
                logging.info(f"Skipping slave at index {idx}: missing deviceID")
                continue
            s_obj = (
                Device.objects.filter(hardware_identifier=sid, deleted_at__isnull=True)
                .select_related("user", "master")
                .first()
            )
            if not s_obj:
                logging.info(
                    f"Ignoring telemetry for unknown slave '{sid}' from master '{master_id}'"
                )
                continue
            # Enforce role and master linkage
            if (
                getattr(s_obj, "device_role", None)
                != getattr(Device, "DeviceRole").SLAVE
            ):
                logging.info(f"Ignoring telemetry for '{sid}': device is not a slave")
                continue
            if s_obj.master_id != master_obj.id:
                logging.info(
                    f"Ignoring telemetry for slave '{sid}': not registered under master '{master_id}'"
                )
                continue

            s_status = sd.get("status")
            s_status = (
                str(s_status).strip()
                if isinstance(s_status, str)
                else (s_status or "alive")
            )
            s_smoke = _to_int(sd.get("smoke"), default=0)
            raw_slave_ts = sd.get("timestamp")
            s_ts_int, s_ts_dt = _to_ts_dt(raw_slave_ts or payload.get("timestamp"))

            # Enforce own timestamp if configured; if slave timestamp is missing or identical
            # to master's timestamp while requirement enabled, skip updating this slave so it
            # naturally becomes offline after freshness window.
            if getattr(settings, "SLAVE_REQUIRE_OWN_TIMESTAMP", True):
                try:
                    # Compare numeric form; if slave ts missing OR equals master ts, treat as stale
                    if raw_slave_ts is None or (
                        m_ts_int is not None and s_ts_int == m_ts_int
                    ):
                        logging.info(
                            f"Skipping slave '{sid}' update: own timestamp missing or not distinct"
                        )
                        continue
                except Exception:
                    pass

            services.ingest_telemetry(
                s_obj,
                smoke_level=s_smoke or 0,
                device_status=s_status or "alive",
                timestamp=s_ts_dt,
            )
            # Use canonical device ID from database for consistent WebSocket broadcasting
            slave_canonical_id = s_obj.hardware_identifier
            devices_for_broadcast.append(
                (
                    s_obj,
                    slave_canonical_id,
                    s_ts_int,
                    s_ts_dt,
                    (s_smoke or 0),
                    (s_status or "alive"),
                )
            )
            if (s_smoke or 0) > threshold:
                group_alarm = True

        # Apply mesh alert to all members of the master's mesh
        try:
            services.apply_mesh_alert(master_obj, group_alarm=group_alarm)
        except Exception as e:
            logging.error(f"apply_mesh_alert failed for master {master_id}: {e}")

        # Now broadcast updates for master and all valid slaves so mesh_alert reflects the applied state
        try:
            for obj, did, ts_i, ts_d, smk, stat in devices_for_broadcast:
                _broadcast_device_update(
                    obj,
                    device_id=did,
                    ts_int=ts_i,
                    ts_dt=ts_d,
                    smoke_val=smk,
                    status_str=stat,
                )
        except Exception:
            pass

        return  # Composite handled

    # Legacy single-device payload path
    device_id = str(payload.get("deviceID", "")).strip()
    timestamp = payload.get("timestamp")
    smoke = payload.get("smoke")
    status = payload.get("status")

    if not device_id:
        raise ValueError("Missing deviceID")

    ts_int, ts_dt = _to_ts_dt(timestamp)
    smoke_int = _to_int(smoke)
    if not isinstance(status, str) or smoke_int is None:
        raise ValueError("Invalid types in payload")

    # Strict ingestion: accept only registered (non-deleted) devices
    device_obj = (
        Device.objects.filter(hardware_identifier=device_id, deleted_at__isnull=True)
        .select_related("user")
        .first()
    )
    if not device_obj:
        logging.info(f"Ignoring telemetry from unknown device '{device_id}'")
        return

    services.ingest_telemetry(
        device_obj,
        smoke_level=smoke_int,
        device_status=status,
        timestamp=ts_dt,
    )
    # Use canonical device ID from database to ensure consistent matching with frontend
    canonical_id = device_obj.hardware_identifier
    _broadcast_device_update(
        device_obj,
        device_id=canonical_id,
        ts_int=ts_int,
        ts_dt=ts_dt,
        smoke_val=smoke_int,
        status_str=status,
    )

    # Legacy path: recompute and apply mesh alert using the device's group.
    # Regression fix: previously, we treated ANY high telemetry within the freshness window
    # as keeping the mesh alert open. For a single device (no slaves) this caused the alert
    # to remain open even after current smoke fell below threshold because the last high
    # telemetry row still existed inside the time window. We now base the decision on the
    # current reading when there is no mesh, and only aggregate historical highs when there
    # are multiple members.
    try:
        master = services.get_master_for_device(device_obj)
        threshold = int(getattr(settings, "SMOKE_ALERT_THRESHOLD", 50))
        freshness = int(getattr(settings, "DEVICE_ONLINE_FRESHNESS_SECONDS", 180))
        recent_since = timezone.now() - dt.timedelta(seconds=freshness)
        member_qs = services.get_group_members(master)
        member_ids = list(member_qs.values_list("id", flat=True))

        if len(member_ids) <= 1:
            # Single device – rely ONLY on the current reading.
            has_any_high = smoke_int > threshold
        else:
            from devices.models import Alert as _Alert, Device as _Dev

            # Filter members to those that are ONLINE (fresh last_seen) before considering any open alerts.
            fresh_cutoff = timezone.now() - dt.timedelta(seconds=freshness)
            online_member_ids = list(
                _Dev.objects.filter(
                    id__in=member_ids, last_seen__gte=fresh_cutoff
                ).values_list("id", flat=True)
            )
            if not online_member_ids:
                has_any_high = False
            else:
                has_any_high = _Alert.objects.filter(
                    device_id__in=online_member_ids,
                    alert_type="smoke_high",
                    status=AlertStatus.OPEN,
                ).exists()

        services.apply_mesh_alert(master, group_alarm=has_any_high)

        # Broadcast mesh state so clients update group alert indicator.
        try:
            channel_layer = get_channel_layer()
            if channel_layer is not None:
                for hid in member_qs.values_list("hardware_identifier", flat=True):
                    async_to_sync(channel_layer.group_send)(
                        "devices",
                        {
                            "type": "device.update",
                            "device": {
                                "deviceID": hid,
                                "mesh_alert": bool(has_any_high),
                            },
                        },
                    )
        except Exception:
            pass
    except Exception as e:
        logging.error(f"apply_mesh_alert (legacy) failed for {device_id}: {e}")


def _populate_devices_cache():
    """Populate the shared device cache with all registered devices on startup.

    This ensures that devices already running and sending telemetry before
    the server starts will be visible on the dashboard immediately when
    WebSocket clients connect, without waiting for new MQTT messages.
    """
    try:
        close_old_connections()
        devices = Device.objects.filter(deleted_at__isnull=True).select_related("user")
        seed_map: Dict[str, Dict[str, Any]] = {}

        for device in devices:
            try:
                # Get the most recent telemetry for this device (if any)
                from devices.models import Telemetry

                latest_telemetry = (
                    Telemetry.objects.filter(device=device)
                    .order_by("-timestamp")
                    .first()
                )

                # Prepare device payload with last known state
                ts_int = None
                timestamp_iso = None
                smoke_val = 0
                status_str = device.status or DeviceStatus.OFFLINE

                if latest_telemetry:
                    ts_int = int(latest_telemetry.timestamp.timestamp())
                    tz = timezone.get_current_timezone()
                    ts_dt_local = latest_telemetry.timestamp.astimezone(tz)
                    timestamp_iso = _fmt12(ts_dt_local)
                    smoke_val = latest_telemetry.smoke_level

                # Build device payload
                device_payload = {
                    MQTTPayloadKeys.DEVICE_ID: device.hardware_identifier,
                    MQTTPayloadKeys.TIMESTAMP: ts_int,
                    "timestamp_iso": timestamp_iso,
                    "received_at_iso": None,
                    MQTTPayloadKeys.SMOKE: smoke_val,
                    MQTTPayloadKeys.STATUS: status_str,
                    "online": bool(device.is_online),
                }

                # Add mesh alert flag
                try:
                    device_payload["mesh_alert"] = bool(_compute_mesh_alert(device))
                except Exception as e:
                    logger.debug(
                        f"Failed to compute mesh alert for device {device.hardware_identifier}: {e}"
                    )
                    device_payload["mesh_alert"] = False

                # Add GPS coordinates if available
                if device.latitude is not None and device.longitude is not None:
                    try:
                        device_payload["latitude"] = float(device.latitude)
                        device_payload["longitude"] = float(device.longitude)
                    except (TypeError, ValueError, Decimal.InvalidOperation):
                        pass

                # Stage for cache population
                seed_map[device.hardware_identifier] = device_payload
                logger.debug(
                    f"Pre-loaded device {device.hardware_identifier} into cache"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to pre-load device {device.hardware_identifier}: {e}"
                )
                continue

        device_cache.replace_all(seed_map)
        logger.info(f"✅ Pre-loaded {len(seed_map)} registered devices into cache")

    except Exception as e:
        logger.error(f"Failed to populate devices cache: {e}", exc_info=True)


def ensure_mqtt_thread():
    """Start MQTT client thread with auto-reconnect and health monitoring.

    This function starts a background thread that:
    - Connects to the MQTT broker
    - Subscribes to telemetry topics
    - Processes incoming device messages
    - Automatically reconnects on failure
    - Tracks connection status for health checks
    """
    global _thread_started
    if _thread_started:
        return
    _thread_started = True

    # Populate the shared device cache with all registered devices on startup
    _populate_devices_cache()

    def get_position(device: Device):
        """Return persisted lat/lon for UI broadcast, if present.

        No fallback jittering; devices without coordinates won't include lat/lon.
        """
        if device.latitude is None or device.longitude is None:
            return None
        return {
            "latitude": float(device.latitude),
            "longitude": float(device.longitude),
        }

    def on_connect(client, userdata, flags, rc):
        """Callback when MQTT client connects to broker."""
        if rc == 0:
            _mqtt_status["connected"] = True
            _mqtt_status["connection_time"] = time.time()
            _mqtt_status["error"] = None
            _mqtt_status["broker"] = settings.MQTT_BROKER
            _mqtt_status["port"] = settings.MQTT_PORT
            logger.info(
                f"✅ MQTT connected to {settings.MQTT_BROKER}:{settings.MQTT_PORT} "
                f"on topic '{settings.MQTT_TOPIC}'"
            )
            try:
                result, _ = client.subscribe(settings.MQTT_TOPIC)
                if result != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(f"Subscribe failed with rc={result}")
                logger.debug("Re-subscribed to telemetry topic after connect")
            except Exception as exc:
                # If we fail the subscription the client keeps running but we'll
                # reconnect on the next retry loop.
                logger.error(f"Failed to subscribe to telemetry topic: {exc}")
        else:
            _mqtt_status["connected"] = False
            error_msgs = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized",
            }
            error_msg = error_msgs.get(rc, f"Unknown error code {rc}")
            _mqtt_status["error"] = error_msg
            logger.error(f"❌ MQTT connection failed: {error_msg} (code {rc})")

    def on_disconnect(client, userdata, rc):
        """Callback when MQTT client disconnects from broker."""
        _mqtt_status["connected"] = False
        if rc != 0:
            logger.warning(
                f"⚠️ MQTT unexpected disconnect (code {rc}). Will auto-reconnect..."
            )
        else:
            logger.info("MQTT disconnected normally")

    def on_message(client, userdata, msg):
        """Callback when MQTT message received."""
        _mqtt_status["last_message_time"] = time.time()
        raw = msg.payload.decode(errors="ignore").strip()
        try:
            close_old_connections()
            payload = json.loads(raw)
            process_payload(payload)
        except (InterfaceError, OperationalError) as e:
            # Database connection went stale; recycle and retry on next message
            close_old_connections()
            logger.error(
                "Database connection issue while processing MQTT message: %s; raw=%s",
                e,
                raw,
            )
        except Exception as e:
            logger.error(f"Failed to process MQTT message: {e}; raw={raw}")

    def run():
        """Main MQTT thread loop with auto-reconnect."""
        while True:
            try:
                logger.info(
                    f"🔄 Attempting MQTT connection to "
                    f"{settings.MQTT_BROKER}:{settings.MQTT_PORT}"
                )

                client = mqtt.Client()
                if settings.MQTT_USER:
                    client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)

                client.on_connect = on_connect
                client.on_disconnect = on_disconnect
                client.on_message = on_message

                # Make reconnects less aggressive in case of broker issues.
                client.reconnect_delay_set(min_delay=1, max_delay=60)

                # Connect and subscribe
                client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)

                # Blocking loop - will exit on disconnect
                client.loop_forever(retry_first_connection=True)

            except Exception as e:
                _mqtt_status["connected"] = False
                _mqtt_status["error"] = str(e)
                logger.error(f"❌ MQTT thread crashed: {e}. Retrying in 10s...")
                time.sleep(10)  # Wait before retry

    t = threading.Thread(target=run, daemon=True, name="MQTT-Client")
    t.start()
    logger.info("🚀 MQTT background thread started")
