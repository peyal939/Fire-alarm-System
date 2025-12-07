"""
Management command to sync the in-memory device cache with the database.

Removes deleted devices from the cache and optionally broadcasts removals.
Use this when devices were deleted via Django Admin and you can't restart the server.

Usage:
    python manage.py sync_device_cache
    python manage.py sync_device_cache --broadcast  # Also notify WebSocket clients
    python manage.py sync_device_cache --dry-run    # Just show what would be removed
"""

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync device cache with database - removes deleted devices from cache"

    def add_arguments(self, parser):
        parser.add_argument(
            "--broadcast",
            action="store_true",
            help="Broadcast device removals to WebSocket clients",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without making changes",
        )

    def handle(self, *args, **options):
        from realtime import device_cache
        from devices.models import Device

        broadcast = options["broadcast"]
        dry_run = options["dry_run"]

        # Get all device IDs currently in cache
        cached_states = device_cache.get_all_states()
        cached_ids = {
            state.get("deviceID") for state in cached_states if state.get("deviceID")
        }

        if not cached_ids:
            self.stdout.write(self.style.SUCCESS("Cache is empty, nothing to sync."))
            return

        self.stdout.write(f"Found {len(cached_ids)} devices in cache")

        # Get all valid (non-deleted) device IDs from database
        valid_ids = set(
            Device.objects.filter(deleted_at__isnull=True).values_list(
                "hardware_identifier", flat=True
            )
        )

        self.stdout.write(f"Found {len(valid_ids)} active devices in database")

        # Find devices in cache that shouldn't be there
        stale_ids = cached_ids - valid_ids

        if not stale_ids:
            self.stdout.write(
                self.style.SUCCESS("Cache is in sync with database. No stale devices.")
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {len(stale_ids)} stale devices to remove:")
        )
        for device_id in stale_ids:
            self.stdout.write(f"  - {device_id}")

        if dry_run:
            self.stdout.write(
                self.style.NOTICE(
                    "Dry run - no changes made. Run without --dry-run to apply."
                )
            )
            return

        # Remove stale devices from cache
        removed_count = 0
        for device_id in stale_ids:
            try:
                device_cache.remove_device(device_id)
                removed_count += 1
                self.stdout.write(f"  Removed {device_id} from cache")

                if broadcast:
                    self._broadcast_removal(device_id)

            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"  Failed to remove {device_id}: {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"Removed {removed_count} stale devices from cache.")
        )

        if broadcast:
            self.stdout.write("Broadcast messages sent to WebSocket clients.")

    def _broadcast_removal(self, device_id: str):
        """Send device removal notification to WebSocket clients."""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

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
                self.stdout.write(f"    Broadcasted removal for {device_id}")
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"    Failed to broadcast {device_id}: {exc}")
            )
