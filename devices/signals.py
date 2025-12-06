"""
Django signals for the devices app.

Handles cache cleanup when devices are deleted (including via Django Admin).
"""

import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_delete, sender="devices.Device")
def on_device_deleted(sender, instance, **kwargs):
    """Clear device from cache and broadcast removal when deleted via any method."""
    from realtime import device_cache

    device_id = getattr(instance, "hardware_identifier", None)
    if not device_id:
        return

    logger.info("Device %s deleted, clearing from cache", device_id)
    device_cache.remove_device(device_id)

    # Broadcast removal to WebSocket clients
    try:
        from realtime.mqtt import broadcast_device_removed

        # Note: broadcast_device_removed also calls remove_device internally,
        # but calling it twice is harmless and ensures the WebSocket message is sent
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
            logger.debug("Broadcasted device removal for %s", device_id)
    except Exception as exc:
        logger.warning("Failed to broadcast device %s removal: %s", device_id, exc)


@receiver(pre_save, sender="devices.Device")
def on_device_soft_delete(sender, instance, **kwargs):
    """
    Detect soft-delete (deleted_at being set) and clear cache.

    This handles the case where soft_delete() is called but the model
    is not actually deleted from the database.
    """
    if not instance.pk:
        return

    # Check if deleted_at is being set (soft delete)
    if instance.deleted_at is not None:
        try:
            from devices.models import Device

            old_instance = Device.objects.filter(pk=instance.pk).first()
            if old_instance and old_instance.deleted_at is None:
                # This is a soft delete - clear the cache
                from realtime import device_cache

                device_id = instance.hardware_identifier
                logger.info("Device %s soft-deleted, clearing from cache", device_id)
                device_cache.remove_device(device_id)

                # Broadcast removal
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
                except Exception as exc:
                    logger.warning(
                        "Failed to broadcast soft-delete for %s: %s", device_id, exc
                    )
        except Exception as exc:
            logger.warning("Error in soft-delete detection for device: %s", exc)
