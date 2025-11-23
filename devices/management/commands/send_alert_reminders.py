from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from devices.alarm_state import schedule_next_reminder
from devices.enums import AlertStatus
from devices.models import Alert, DeviceAlarmState

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send reminder push notifications for unresolved fire alerts."

    def handle(self, *args, **options):
        reminder_states = (
            DeviceAlarmState.objects.select_related(
                "device", "device__user", "active_alert"
            )
            .filter(
                next_reminder_at__isnull=False, next_reminder_at__lte=timezone.now()
            )
            .order_by("next_reminder_at")
        )

        if not reminder_states.exists():
            self.stdout.write("No alert reminders due.")
            return

        sent = 0
        skipped = 0
        ack_escalation_seconds = max(
            int(getattr(settings, "ALERT_ACK_ESCALATION_SECONDS", 0)), 0
        )

        try:
            from notifications.services import FCMService
        except ImportError as exc:  # pragma: no cover - optional dependency safeguard
            raise CommandError(f"Notifications app unavailable: {exc}")

        for state in reminder_states:
            alert = state.active_alert
            if not alert or alert.status != AlertStatus.OPEN:
                state.next_reminder_at = None
                state.save(update_fields=["next_reminder_at", "updated_at"])
                skipped += 1
                continue

            device = alert.device
            user = device.user
            device_name = device.device_name or device.hardware_identifier

            with transaction.atomic():
                # Re-fetch with lock to avoid duplicate reminders under concurrency
                locked_state = (
                    DeviceAlarmState.objects.select_for_update()
                    .select_related("active_alert", "device", "device__user")
                    .get(pk=state.pk)
                )
                alert = locked_state.active_alert
                if not alert or alert.status != AlertStatus.OPEN:
                    locked_state.next_reminder_at = None
                    locked_state.save(update_fields=["next_reminder_at", "updated_at"])
                    skipped += 1
                    continue

                now = timezone.now()
                if alert.acknowledged_at:
                    if ack_escalation_seconds <= 0:
                        schedule_next_reminder(alert)
                        skipped += 1
                        continue
                    ack_age = (now - alert.acknowledged_at).total_seconds()
                    if ack_age < ack_escalation_seconds:
                        schedule_next_reminder(alert)
                        skipped += 1
                        continue

                try:
                    FCMService.send_alert_notification(
                        user=user,
                        device_name=device_name,
                        alert_type=alert.alert_type,
                        alert_id=alert.id,
                        is_reminder=True,
                    )
                    sent += 1
                except Exception as exc:
                    logger.error(
                        "Failed to send reminder for alert %s: %s",
                        alert.id,
                        exc,
                        exc_info=True,
                    )
                    skipped += 1
                else:
                    send_time = timezone.now()
                    alert.last_reminder_at = send_time
                    alert.reminder_count += 1
                    alert.save(update_fields=["last_reminder_at", "reminder_count"])
                finally:
                    schedule_next_reminder(alert)

        self.stdout.write(
            self.style.SUCCESS(
                f"Alert reminder run complete. Sent: {sent}, skipped: {skipped}."
            )
        )
