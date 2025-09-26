import json
from channels.generic.websocket import AsyncWebsocketConsumer

# In-memory store for device state
DEVICES = {}
WEBSOCKETS = set()


class DeviceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        WEBSOCKETS.add(self)
        await self.channel_layer.group_add("devices", self.channel_name)
        # Send snapshot
        for d in DEVICES.values():
            await self.send(text_data=json.dumps(d))

    async def disconnect(self, close_code):
        WEBSOCKETS.discard(self)
        await self.channel_layer.group_discard("devices", self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Keep alive, ignore payload
        pass

    async def device_update(self, event):
        await self.send(text_data=json.dumps(event["device"]))
