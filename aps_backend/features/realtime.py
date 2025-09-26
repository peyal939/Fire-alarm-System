import asyncio
import json
import logging
import random
import threading
from typing import Any, Dict, Set

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.websockets import WebSocketDisconnect
from fastapi import Request

import paho.mqtt.client as mqtt

from ..core.config import get_settings


def register_realtime(app: FastAPI) -> None:
    """Wire UI routes, static files, WebSocket, and MQTT background consumer.

    This reproduces the behavior of the former top-level app.py.
    """

    settings = get_settings()

    # In-memory state
    app.state.devices = {}
    app.state.websockets = set()
    app.state.device_positions = {}

    # Map defaults
    BASE_LAT = settings.MAP_BASE_LAT
    BASE_LON = settings.MAP_BASE_LON
    POSITION_JITTER = settings.MAP_JITTER

    # Static and templates
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")

    # Routes: / and /login
    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request):
        return templates.TemplateResponse("login.html", {"request": request})

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    # Helpers
    def get_device_position(device_id: str):
        pos = app.state.device_positions.get(device_id)
        if pos is None:
            lat = BASE_LAT + random.uniform(-POSITION_JITTER, POSITION_JITTER)
            lon = BASE_LON + random.uniform(-POSITION_JITTER, POSITION_JITTER)
            pos = {"latitude": lat, "longitude": lon}
            app.state.device_positions[device_id] = pos
        return pos

    async def send_update_to_websockets(device: Dict[str, Any]):
        for ws in list(app.state.websockets):
            try:
                await ws.send_json(device)
            except WebSocketDisconnect:
                app.state.websockets.discard(ws)
            except Exception as e:  # pragma: no cover
                logging.warning(f"WebSocket send failed: {e}; dropping socket")
                app.state.websockets.discard(ws)

    async def handle_device_update(device: Dict[str, Any]):
        device_id = str(device["deviceID"]).strip()
        if "latitude" not in device or "longitude" not in device:
            pos = get_device_position(device_id)
            device.setdefault("latitude", pos["latitude"])  # floats OK for frontend
            device.setdefault("longitude", pos["longitude"])  # floats OK for frontend

        app.state.devices[device_id] = device
        await send_update_to_websockets(device)

    # WebSocket endpoint
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        app.state.websockets.add(ws)
        # Send all known devices on connect
        for device in app.state.devices.values():
            await ws.send_json(device)
        try:
            while True:
                # Keep connection alive; ignore incoming
                await ws.receive_text()
        except WebSocketDisconnect:
            app.state.websockets.discard(ws)
        except Exception as e:  # pragma: no cover
            logging.warning(f"WebSocket connection error: {e}")
            app.state.websockets.discard(ws)

    # MQTT handling
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

            device = {
                "deviceID": device_id,
                "timestamp": timestamp,
                "smoke": smoke,
                "status": status,
            }

            loop = getattr(app.state, "loop", None)
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(handle_device_update(device), loop)
            else:
                # Fallback; should be rare
                app.state.devices[device_id] = device
                logging.warning(
                    "Event loop not ready; updated devices directly from MQTT thread"
                )
        except Exception as e:  # pragma: no cover
            logging.error(f"Failed to process MQTT message: {e}; raw={raw}")

    @app.on_event("startup")
    async def startup_event():
        # Capture running loop for thread-safe scheduling
        app.state.loop = asyncio.get_running_loop()

        def mqtt_loop():
            client = mqtt.Client()
            if settings.MQTT_USER:
                client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)
            client.on_message = on_message
            client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
            client.subscribe(settings.MQTT_TOPIC)
            client.loop_forever()

        t = threading.Thread(target=mqtt_loop, daemon=True)
        t.start()
