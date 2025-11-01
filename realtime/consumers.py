import asyncio
import json
import logging
from contextlib import suppress

from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer

# In-memory store for device state
DEVICES = {}
WEBSOCKETS = set()
logger = logging.getLogger(__name__)


def _heartbeat_interval() -> int:
    default_interval = 20
    try:
        value = int(
            getattr(settings, "WEBSOCKET_SERVER_HEARTBEAT_SECONDS", default_interval)
        )
        return max(value, 0)
    except Exception:
        return default_interval


class DeviceConsumer(AsyncWebsocketConsumer):
    heartbeat_task: asyncio.Task | None = None

    async def connect(self):
        await self.accept()
        WEBSOCKETS.add(self)
        await self.channel_layer.group_add("devices", self.channel_name)
        for d in DEVICES.values():
            await self.send(text_data=json.dumps(d))
        interval = _heartbeat_interval()
        if interval > 0:
            self.heartbeat_task = asyncio.create_task(self._heartbeat(interval))

    async def disconnect(self, close_code):
        WEBSOCKETS.discard(self)
        await self.channel_layer.group_discard("devices", self.channel_name)
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.heartbeat_task
            self.heartbeat_task = None

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            payload = json.loads(text_data)
        except (TypeError, ValueError):
            return
        msg_type = (payload or {}).get("type")
        if msg_type == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))
        elif msg_type == "pong":
            return

    async def device_update(self, event):
        """Handle device update messages from the channel layer.

        Includes error handling to prevent channel overflow from crashing consumers.
        """
        try:
            await self.send(text_data=json.dumps(event["device"]))
        except Exception as e:
            # Non-fatal: if sending fails, log but keep connection alive
            logger.warning(f"Failed to send device update to WebSocket: {e}")

    async def device_removed(self, event):
        payload = event.get("payload", {}) or {}
        if "type" not in payload:
            payload["type"] = "device_removed"
        if "deviceID" not in payload:
            payload["deviceID"] = event.get("device_id")
        try:
            await self.send(text_data=json.dumps(payload))
        except Exception as e:
            logger.warning(f"Failed to send device removal to WebSocket: {e}")

    async def _heartbeat(self, interval: int):
        try:
            while True:
                await asyncio.sleep(interval)
                await self.send(text_data=json.dumps({"type": "ping"}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.debug("DeviceConsumer heartbeat send failed: %s", exc)
