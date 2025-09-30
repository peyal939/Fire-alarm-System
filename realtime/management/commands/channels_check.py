import asyncio
import json
import os
import sys
import time
import uuid

from django.core.management.base import BaseCommand

try:
    from channels.layers import get_channel_layer
except Exception as e:  # pragma: no cover
    get_channel_layer = None


class Command(BaseCommand):
    help = "Verify Django Channels channel layer connectivity (Redis) with a simple send/receive round trip."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=float,
            default=3.0,
            help="Seconds to wait for the message round trip",
        )

    def handle(self, *args, **options):
        if get_channel_layer is None:
            self.stderr.write("channels is not installed or import failed")
            sys.exit(2)

        layer = get_channel_layer()
        if layer is None:
            self.stderr.write("No channel layer configured. Did you set REDIS_URL?")
            sys.exit(2)

        # Optional: show where we're connecting
        redis_url = os.getenv("REDIS_URL", "<in-memory>")
        self.stdout.write(f"Using channel layer via: {redis_url}")

        async def _check():
            # Create a new channel to listen on
            ch_name = await layer.new_channel("healthcheck.")

            # Unique payload
            token = str(uuid.uuid4())
            payload = {"type": "health.message", "token": token, "ts": time.time()}

            # Send to ourselves
            await layer.send(ch_name, {"type": "health.message", "payload": payload})

            # Receive back
            start = time.time()
            while time.time() - start < options["timeout"]:
                message = await layer.receive(ch_name)
                if message and isinstance(message, dict):
                    got = message.get("payload", {})
                    if got.get("token") == token:
                        return True, got
            return False, None

        ok, data = asyncio.run(_check())
        if ok:
            self.stdout.write(self.style.SUCCESS("Channels/Redis healthcheck OK"))
            if data:
                self.stdout.write(json.dumps(data))
            sys.exit(0)
        else:
            self.stderr.write(
                "Failed to complete channel layer round-trip within timeout"
            )
            sys.exit(1)
