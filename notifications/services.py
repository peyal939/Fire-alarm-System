"""Service layer for sending Firebase Cloud Messaging push notifications."""

import logging
from typing import Optional, Dict, Any, List

from django.contrib.auth import get_user_model
from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError

from .firebase import is_firebase_initialized
from .models import FCMDevice, NotificationLog

logger = logging.getLogger(__name__)
User = get_user_model()


class FCMService:
    """Service for sending push notifications via Firebase Cloud Messaging."""

    @staticmethod
    def send_to_user(
        user,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
    ) -> Dict[str, Any]:
        """Send push notification to all active devices of a user.

        Args:
            user: User instance to send notification to
            title: Notification title
            body: Notification body/message
            data: Optional dictionary of custom data to send with notification
            sound: Sound to play (default, alert_sound, etc.)

        Returns:
            Dictionary with success count, failure count, and invalid tokens
        """
        if not is_firebase_initialized():
            logger.warning(
                f"Firebase not initialized. Cannot send notification to user {user.id}"
            )
            return {"success": 0, "failure": 0, "invalid_tokens": []}

        # Get all active FCM devices for this user
        devices = FCMDevice.objects.filter(user=user, active=True)

        if not devices.exists():
            logger.info(f"No active FCM devices found for user {user.id}")
            return {"success": 0, "failure": 0, "invalid_tokens": []}

        # Convert all data values to strings (FCM requirement)
        string_data = {}
        if data:
            string_data = {k: str(v) for k, v in data.items()}

        results = {"success": 0, "failure": 0, "invalid_tokens": []}

        for device in devices:
            try:
                # Build the notification message
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=body,
                    ),
                    data=string_data,
                    token=device.registration_token,
                    android=messaging.AndroidConfig(
                        priority="high",
                        notification=messaging.AndroidNotification(
                            sound=sound,
                            channel_id="fire_alerts",  # Must match mobile app channel
                            priority="high",
                        ),
                    ),
                    apns=messaging.APNSConfig(
                        payload=messaging.APNSPayload(
                            aps=messaging.Aps(
                                sound=sound,
                                badge=1,
                                content_available=True,
                            )
                        )
                    ),
                )

                # Send the message
                response = messaging.send(message)

                # Log success
                NotificationLog.objects.create(
                    user=user,
                    fcm_device=device,
                    title=title,
                    body=body,
                    data=data,
                    status="sent",
                )

                # Update last used timestamp
                from django.utils import timezone

                device.last_used_at = timezone.now()
                device.save(update_fields=["last_used_at"])

                results["success"] += 1
                logger.info(
                    f"Notification sent successfully to device {device.id}: {response}"
                )

            except messaging.UnregisteredError:
                # Token is invalid or unregistered - deactivate it
                logger.warning(
                    f"Invalid FCM token for device {device.id}, deactivating"
                )
                device.active = False
                device.save(update_fields=["active"])
                results["invalid_tokens"].append(device.registration_token)
                results["failure"] += 1

                NotificationLog.objects.create(
                    user=user,
                    fcm_device=device,
                    title=title,
                    body=body,
                    data=data,
                    status="invalid_token",
                    error_message="Token unregistered or invalid",
                )

            except FirebaseError as e:
                # Other Firebase errors
                logger.error(
                    f"Firebase error sending to device {device.id}: {e}", exc_info=True
                )
                results["failure"] += 1

                NotificationLog.objects.create(
                    user=user,
                    fcm_device=device,
                    title=title,
                    body=body,
                    data=data,
                    status="failed",
                    error_message=str(e),
                )

            except Exception as e:
                # Unexpected errors
                logger.error(
                    f"Unexpected error sending notification to device {device.id}: {e}",
                    exc_info=True,
                )
                results["failure"] += 1

                NotificationLog.objects.create(
                    user=user,
                    fcm_device=device,
                    title=title,
                    body=body,
                    data=data,
                    status="failed",
                    error_message=str(e),
                )

        return results

    @staticmethod
    def send_alert_notification(
        user,
        device_name: str,
        alert_type: str,
        alert_id: int,
        *,
        is_reminder: bool = False,
    ) -> Dict[str, Any]:
        """Send a fire alert notification to user's devices.

        Args:
            user: User to notify
            device_name: Name of the device that triggered the alert
            alert_type: Type of alert (e.g., 'smoke_high')
            alert_id: ID of the alert record
            is_reminder: Whether this push is a reminder for an ongoing alert

        Returns:
            Dictionary with send results
        """
        if is_reminder:
            title = "Fire Alert Reminder"
            body = f"Ongoing smoke alert on {device_name}!"
        else:
            title = "Fire Alert!"
            body = f"High smoke detected on {device_name}!"

        data = {
            "type": "fire_alert",
            "alert_id": str(alert_id),
            "alert_type": alert_type,
            "device_name": device_name,
            "priority": "high",
            "is_reminder": "true" if is_reminder else "false",
        }

        return FCMService.send_to_user(
            user=user,
            title=title,
            body=body,
            data=data,
            sound="alert_sound",  # Custom sound - mobile app must have this file
        )

    @staticmethod
    def send_device_offline_notification(
        user, device_name: str, device_id: int
    ) -> Dict[str, Any]:
        """Send notification when a device goes offline.

        Args:
            user: User to notify
            device_name: Name of the offline device
            device_id: ID of the device

        Returns:
            Dictionary with send results
        """
        title = "Device Offline"
        body = f"{device_name} is now offline"

        data = {
            "type": "device_offline",
            "device_id": str(device_id),
            "device_name": device_name,
        }

        return FCMService.send_to_user(
            user=user, title=title, body=body, data=data, sound="default"
        )

    @staticmethod
    def send_test_notification(user) -> Dict[str, Any]:
        """Send a test notification to verify FCM setup.

        Args:
            user: User to send test notification to

        Returns:
            Dictionary with send results
        """
        title = "Test Notification"
        body = "Your fire alarm notifications are working correctly!"

        data = {
            "type": "test",
        }

        return FCMService.send_to_user(
            user=user, title=title, body=body, data=data, sound="default"
        )
