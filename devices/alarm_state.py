"""Alarm state handling helpers for smoke alerts and reminders."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .constants import AlertType
from .enums import AlertStatus
from .models import Alert, Device, DeviceAlarmState

logger = logging.getLogger(__name__)


@dataclass
class AlarmStateResult:
    """Outcome of processing a telemetry reading for a device."""

    alert: Optional[Alert]
    created: bool = False
    resolved: bool = False


def _get_state_for_update(device: Device) -> DeviceAlarmState:
    state, _ = DeviceAlarmState.objects.select_for_update().get_or_create(
        device=device,
        defaults={
            "safe_reading_streak": 0,
            "next_reminder_at": None,
            "active_alert": None,
        },
    )
    return state


def _compute_next_reminder(alert: Alert) -> Optional[datetime]:
    interval_seconds = max(
        int(getattr(settings, "ALERT_REMINDER_INTERVAL_SECONDS", 0)), 0
    )
    if interval_seconds <= 0:
        return None
    max_count = max(int(getattr(settings, "ALERT_REMINDER_MAX_COUNT", 0)), 0)
    if max_count and alert.reminder_count >= max_count:
        return None
    now = timezone.now()
    ack_escalation_seconds = max(
        int(getattr(settings, "ALERT_ACK_ESCALATION_SECONDS", 0)), 0
    )
    if alert.acknowledged_at:
        if ack_escalation_seconds <= 0:
            return None
        ack_due = alert.acknowledged_at + timedelta(seconds=ack_escalation_seconds)
        if alert.last_reminder_at and alert.last_reminder_at >= ack_due:
            return now + timedelta(seconds=interval_seconds)
        return max(ack_due, now)
    return now + timedelta(seconds=interval_seconds)


def record_high_smoke(
    device: Device, *, observed_at: Optional[datetime] = None
) -> AlarmStateResult:
    """Record that the device is experiencing high smoke.

    Returns whether a new alert was created and should trigger a push notification.
    """

    observed_at = observed_at or timezone.now()

    with transaction.atomic():
        state = _get_state_for_update(device)
        alert = state.active_alert
        if (
            not alert
            or alert.status != AlertStatus.OPEN
            or alert.alert_type != AlertType.SMOKE_HIGH
        ):
            alert = (
                Alert.objects.filter(
                    device=device,
                    alert_type=AlertType.SMOKE_HIGH,
                    status=AlertStatus.OPEN,
                )
                .order_by("-triggered_at")
                .first()
            )
        created = False

        if not alert:
            alert = Alert.objects.create(
                device=device,
                alert_type=AlertType.SMOKE_HIGH,
                status=AlertStatus.OPEN,
                triggered_at=observed_at,
                last_triggered_at=observed_at,
            )
            created = True
        else:
            fields = []
            if alert.last_triggered_at != observed_at:
                alert.last_triggered_at = observed_at
                fields.append("last_triggered_at")
            if alert.status != AlertStatus.OPEN:
                alert.status = AlertStatus.OPEN
                fields.append("status")
            if fields:
                alert.save(update_fields=fields)

        state.active_alert = alert
        state.safe_reading_streak = 0
        state.next_reminder_at = _compute_next_reminder(alert)
        state.save(
            update_fields=[
                "active_alert",
                "safe_reading_streak",
                "next_reminder_at",
                "updated_at",
            ]
        )

    return AlarmStateResult(alert=alert, created=created, resolved=False)


def record_safe_smoke(
    device: Device, *, observed_at: Optional[datetime] = None
) -> AlarmStateResult:
    """Record a safe/normal smoke reading for the device."""

    observed_at = observed_at or timezone.now()
    required_streak = max(
        int(getattr(settings, "ALERT_AUTO_CLEAR_NORMAL_READINGS", 3)), 1
    )

    with transaction.atomic():
        state = _get_state_for_update(device)
        alert = state.active_alert
        if not alert or alert.status != AlertStatus.OPEN:
            alert = (
                Alert.objects.filter(
                    device=device,
                    alert_type=AlertType.SMOKE_HIGH,
                    status=AlertStatus.OPEN,
                )
                .order_by("-triggered_at")
                .first()
            )
            if alert:
                state.active_alert = alert
                state.save(update_fields=["active_alert", "updated_at"])
        if not alert or alert.status != AlertStatus.OPEN:
            if state.safe_reading_streak:
                state.safe_reading_streak = 0
                state.save(update_fields=["safe_reading_streak", "updated_at"])
            return AlarmStateResult(alert=alert, created=False, resolved=False)

        state.safe_reading_streak += 1
        if state.safe_reading_streak < required_streak:
            state.save(update_fields=["safe_reading_streak", "updated_at"])
            return AlarmStateResult(alert=alert, created=False, resolved=False)

        # Auto-resolve alert
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = observed_at
        alert.save(update_fields=["status", "resolved_at"])

        state.active_alert = None
        state.safe_reading_streak = 0
        state.next_reminder_at = None
        state.save(
            update_fields=[
                "active_alert",
                "safe_reading_streak",
                "next_reminder_at",
                "updated_at",
            ]
        )

    return AlarmStateResult(alert=alert, created=False, resolved=True)


def reset_state_for_alert(alert: Alert) -> None:
    """Clear the alarm state if the alert is no longer active."""

    try:
        state = alert.device.alarm_state
    except DeviceAlarmState.DoesNotExist:
        return

    if state.active_alert_id != alert.id:
        return

    state.active_alert = None
    state.safe_reading_streak = 0
    state.next_reminder_at = None
    state.save(
        update_fields=[
            "active_alert",
            "safe_reading_streak",
            "next_reminder_at",
            "updated_at",
        ]
    )


def schedule_next_reminder(alert: Alert) -> None:
    """Recompute and persist the next reminder timestamp for an alert."""
    state, _ = DeviceAlarmState.objects.get_or_create(
        device=alert.device,
        defaults={
            "active_alert": alert if alert.status == AlertStatus.OPEN else None,
            "safe_reading_streak": 0,
            "next_reminder_at": None,
        },
    )

    if alert.status == AlertStatus.OPEN and state.active_alert_id != alert.id:
        state.active_alert = alert

    if alert.status != AlertStatus.OPEN:
        state.next_reminder_at = None
    else:
        state.next_reminder_at = _compute_next_reminder(alert)

    state.save(update_fields=["active_alert", "next_reminder_at", "updated_at"])
