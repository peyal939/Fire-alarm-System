import json
import logging
import threading
import datetime as dt

import paho.mqtt.client as mqtt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models

from django.conf import settings
from django.utils import timezone

from devices.models import Device
from devices import services
from .consumers import DEVICES

_thread_started = False


def _fmt12(dtobj: dt.datetime) -> str:
    s = dtobj.strftime("%d %b %Y, %I:%M:%S %p")
    return s.replace("AM", "am").replace("PM", "pm")


def _to_int(value, default=None):
    try:
        if isinstance(value, str):
            value = value.strip()
        return int(value)
    except Exception:
        return default


def _to_ts_dt(ts_val):
    tz = timezone.get_current_timezone()
    ts_int = _to_int(ts_val)
    if ts_int is None:
        return None, timezone.now()
    try:
        return ts_int, dt.datetime.fromtimestamp(ts_int, tz=tz)
    except Exception:
        return ts_int, timezone.now()


def _compute_mesh_alert(device_obj: Device) -> bool:
    """True if any device in this device's mesh has an open smoke_high alert.

    Mesh: master + slaves. For slaves, find their master; if no master, treat self as master.
    """
    try:
        from devices.models import Alert

        master = (
            device_obj
            if device_obj.device_role == Device.DeviceRole.MASTER
            else (device_obj.master or device_obj)
        )
        member_ids = list(
            Device.objects.filter(deleted_at__isnull=True)
            .filter(models.Q(id=master.id) | models.Q(master_id=master.id))
            .values_list("id", flat=True)
        )
        if not member_ids:
            return False
        return Alert.objects.filter(
            device_id__in=member_ids,
            alert_type="smoke_high",
            status=Alert.Status.OPEN,
        ).exists()
    except Exception:
        return False


def _broadcast_device_update(
    device_obj: Device,
    *,
    device_id: str,
    ts_int: int | None,
    ts_dt: dt.datetime,
    smoke_val: int,
    status_str: str,
):
    # Persisted coords if any
    pos = None
    try:
        if device_obj.latitude is not None and device_obj.longitude is not None:
            pos = {
                "latitude": float(device_obj.latitude),
                "longitude": float(device_obj.longitude),
            }
    except Exception:
        pos = None

    # Prepare local timestamps
    try:
        tz = timezone.get_current_timezone()
        ts_dt_local = ts_dt.astimezone(tz)
        rec_local = timezone.now().astimezone(tz)
        timestamp_iso = _fmt12(ts_dt_local)
        received_at_iso = _fmt12(rec_local)
    except Exception:
        timestamp_iso = None
        received_at_iso = None

    device_payload = {
        "deviceID": device_id,
        "timestamp": ts_int,
        "timestamp_iso": timestamp_iso,
        "received_at_iso": received_at_iso,
        "smoke": smoke_val,
        "status": status_str,
    }
    # Include mesh alert flag so clients can reflect group state reliably
    try:
        device_payload["mesh_alert"] = bool(_compute_mesh_alert(device_obj))
    except Exception:
        pass
    if pos is not None:
        device_payload["latitude"] = pos["latitude"]
        device_payload["longitude"] = pos["longitude"]

    DEVICES[device_id] = device_payload
    try:
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                "devices", {"type": "device.update", "device": device_payload}
            )
    except Exception:
        # Non-fatal in tests or when channels is not configured
        pass


def process_payload(payload: dict) -> None:
    """Process an already-parsed MQTT payload dict.

    Supports both legacy single-device and composite master/slave payloads.
    Safe to call from tests.
    """
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
        devices_for_broadcast = [
            (
                master_obj,
                master_id,
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
            s_ts_int, s_ts_dt = _to_ts_dt(
                sd.get("timestamp") or payload.get("timestamp")
            )

            services.ingest_telemetry(
                s_obj,
                smoke_level=s_smoke or 0,
                device_status=s_status or "alive",
                timestamp=s_ts_dt,
            )
            devices_for_broadcast.append(
                (
                    s_obj,
                    sid,
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
    _broadcast_device_update(
        device_obj,
        device_id=device_id,
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
            # Multi-device mesh: evaluate CURRENT readings of each member this cycle.
            # Rationale: relying on historical telemetry within a time window caused
            # alerts to linger after values dropped. We now decide the mesh alert
            # strictly by the current readings seen in this ingestion batch (legacy
            # single-device path only has one reading, but mesh members will each
            # send their own messages over time). For members other than the current
            # device we fall back to their open smoke_high alerts to infer if they
            # are still high (since their message may not be in this exact payload).
            from devices.models import Alert as _Alert

            # Determine if ANY member currently still has an open smoke_high alert.
            open_any = _Alert.objects.filter(
                device_id__in=member_ids,
                alert_type="smoke_high",
                status=_Alert.Status.OPEN,
            ).exists()
            # The current reading may have dropped; if this device's reading is low we
            # let the service layer (ingest_telemetry) resolve its own alert already.
            # has_any_high should reflect post-resolution state: combine open alerts
            # across mesh after this device's potential resolution.
            has_any_high = open_any

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


def ensure_mqtt_thread():
    global _thread_started
    if _thread_started:
        return
    _thread_started = True

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

    def on_message(client, userdata, msg):
        raw = msg.payload.decode(errors="ignore").strip()
        try:
            payload = json.loads(raw)
            process_payload(payload)
        except Exception as e:
            logging.error(f"Failed to process MQTT message: {e}; raw={raw}")

    def run():
        client = mqtt.Client()
        if settings.MQTT_USER:
            client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)
        client.on_message = on_message
        client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
        client.subscribe(settings.MQTT_TOPIC)
        client.loop_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()
