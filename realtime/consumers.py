import asyncio
import json
import logging
from contextlib import suppress

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from channels.generic.websocket import AsyncWebsocketConsumer

from . import device_cache
from devices.models import Device

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner_cache: dict[str, int | None] = {}
        self._subscription_cache: dict[str, bool] = {}

    async def connect(self):
        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        await self.accept()
        WEBSOCKETS.add(self)
        await self.channel_layer.group_add("devices", self.channel_name)
        
        def _get_initial_states():
            try:
                return device_cache.get_all_states()
            finally:
                close_old_connections()
        
        initial_states = await sync_to_async(_get_initial_states)()
        for payload in initial_states:
            if await self._can_view_payload(payload):
                await self.send(text_data=json.dumps(payload))
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
        payload = event.get("device") or {}
        if not await self._can_view_payload(payload):
            return
        try:
            await self.send(text_data=json.dumps(payload))
        except Exception as e:
            # Non-fatal: if sending fails, log but keep connection alive
            logger.warning(f"Failed to send device update to WebSocket: {e}")

    async def device_removed(self, event):
        payload = event.get("payload", {}) or {}
        if "type" not in payload:
            payload["type"] = "device_removed"
        if "deviceID" not in payload:
            payload["deviceID"] = event.get("device_id")
        device_id = payload.get("deviceID")
        if device_id and not await self._can_view_device_id(device_id):
            return
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

    def _user_has_admin_scope(self) -> bool:
        user = self.scope.get("user")
        if not user:
            return False
        role = (getattr(user, "role", "") or "").lower()
        return bool(getattr(user, "is_superuser", False) or role == "superadmin")

    async def _get_owner_id_for_payload(self, payload: dict) -> int | None:
        owner_id = payload.get("owner_id")
        device_id = payload.get("deviceID")
        if owner_id is not None:
            if device_id:
                self._owner_cache[device_id] = owner_id
            return owner_id
        if not device_id:
            return None
        cached = self._owner_cache.get(device_id)
        if cached is not None:
            return cached

        def _fetch_owner_id():
            try:
                return Device.objects.filter(
                    hardware_identifier=device_id,
                    deleted_at__isnull=True,
                ).values_list("user_id", flat=True).first()
            finally:
                close_old_connections()

        owner_id = await sync_to_async(_fetch_owner_id)()
        if owner_id is not None:
            self._owner_cache[device_id] = owner_id
            payload["owner_id"] = owner_id
            if len(payload.keys()) > 1:
                def _set_state():
                    try:
                        device_cache.set_device_state(device_id, payload)
                    finally:
                        close_old_connections()
                await sync_to_async(_set_state)()
        return owner_id

    async def _can_view_payload(self, payload: dict) -> bool:
        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            return False
        if self._user_has_admin_scope():
            device_id = payload.get("deviceID")
            if device_id and payload.get("owner_id") is not None:
                self._owner_cache[device_id] = payload["owner_id"]
            return True
        owner_id = await self._get_owner_id_for_payload(payload)
        if owner_id != getattr(user, "id", None):
            return False
        return await self._check_subscription_access(payload.get("deviceID"))

    async def _can_view_device_id(self, device_id: str | None) -> bool:
        if not device_id:
            return False
        user = self.scope.get("user")
        if not getattr(user, "is_authenticated", False):
            return False
        if self._user_has_admin_scope():
            return True
        owner_id = self._owner_cache.get(device_id)
        if owner_id is None:
            owner_id = await self._get_owner_id_for_payload({"deviceID": device_id})
        if owner_id != getattr(user, "id", None):
            return False
        return await self._check_subscription_access(device_id)

    async def _check_subscription_access(self, device_id: str) -> bool:
        if not device_id:
            return False

        # Check cache
        if device_id in self._subscription_cache:
            return self._subscription_cache[device_id]

        # DB check
        has_access = await sync_to_async(self._db_check_subscription)(device_id)
        self._subscription_cache[device_id] = has_access
        return has_access

    def _db_check_subscription(self, device_id: str) -> bool:
        from devices.views import _subscription_access_q

        try:
            now = timezone.now()
            return (
                Device.objects.filter(
                    hardware_identifier=device_id, deleted_at__isnull=True
                )
                .filter(_subscription_access_q(relation="subscription", now=now))
                .exists()
            )
        finally:
            close_old_connections()
