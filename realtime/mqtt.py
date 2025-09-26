import asyncio
import json
import logging
import random
import threading
import time

import paho.mqtt.client as mqtt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.conf import settings
from .consumers import DEVICES

_thread_started = False


def ensure_mqtt_thread():
    global _thread_started
    if _thread_started:
        return
    _thread_started = True

    def get_position(device_id: str):
        # Simple lazy map jitter (not persisted)
        if not hasattr(ensure_mqtt_thread, "positions"):
            ensure_mqtt_thread.positions = {}
        positions = ensure_mqtt_thread.positions
        if device_id not in positions:
            lat = settings.MAP_BASE_LAT + random.uniform(
                -settings.MAP_JITTER, settings.MAP_JITTER
            )
            lon = settings.MAP_BASE_LON + random.uniform(
                -settings.MAP_JITTER, settings.MAP_JITTER
            )
            positions[device_id] = {"latitude": lat, "longitude": lon}
        return positions[device_id]

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

            # enrich missing lat/lon (client expects possibly present)
            pos = get_position(device_id)
            device = {
                "deviceID": device_id,
                "timestamp": timestamp,
                "smoke": smoke,
                "status": status,
                "latitude": pos["latitude"],
                "longitude": pos["longitude"],
            }

            DEVICES[device_id] = device
            # Fan out via channel layer to all WS consumers
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "devices", {"type": "device.update", "device": device}
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
