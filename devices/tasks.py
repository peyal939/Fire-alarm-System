from __future__ import annotations

from celery import shared_task
from django.core.management import call_command


@shared_task(bind=True, ignore_result=True)
def send_alert_reminders_task(self) -> None:
    """Run the reminder management command via Celery."""
    call_command("send_alert_reminders")
