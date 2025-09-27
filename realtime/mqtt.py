import asyncio
import json
import logging
import random
import threading
import time
import datetime as dt

import paho.mqtt.client as mqtt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.conf import settings
from django.utils import timezone

from devices.models import Device
from devices import services
from .consumers import DEVICES

_thread_started = False


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
            device_id = str(payload.get("deviceID", "")).strip()
            timestamp = payload.get("timestamp")
            smoke = payload.get("smoke")
            status = payload.get("status")

            if not device_id:
                raise ValueError("Missing deviceID")

            if isinstance(timestamp, str):
                timestamp = int(timestamp)
            if isinstance(smoke, str):
                smoke = int(smoke)
            if (
                not isinstance(timestamp, int)
                or not isinstance(smoke, int)
                or not isinstance(status, str)
            ):
                raise ValueError("Invalid types in payload")

            # Strict ingestion: accept only registered (non-deleted) devices
            device_obj = (
                Device.objects.filter(
                    hardware_identifier=device_id, deleted_at__isnull=True
                )
                .select_related("user")
                .first()
            )
            if not device_obj:
                logging.info(f"Ignoring telemetry from unknown device '{device_id}'")
                return

            # Persist telemetry + update device + alerts via shared service
            try:
                tz = timezone.get_current_timezone()
                ts_dt = dt.datetime.fromtimestamp(int(timestamp), tz=tz)
            except Exception:
                ts_dt = timezone.now()
            services.ingest_telemetry(
                device_obj,
                smoke_level=smoke,
                device_status=status,
                timestamp=ts_dt,
            )

            # Broadcast to websocket consumers (include coords)
            pos = get_position(device_obj)
            device_payload = {
                "deviceID": device_id,
                "timestamp": timestamp,
                "smoke": smoke,
                "status": status,
            }
            if pos is not None:
                device_payload["latitude"] = pos["latitude"]
                device_payload["longitude"] = pos["longitude"]
            DEVICES[device_id] = device_payload
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "devices", {"type": "device.update", "device": device_payload}
            )
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
