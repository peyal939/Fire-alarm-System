from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import DeviceSubscription
from . import services

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="subscriptions.generate_due_charges")
def generate_due_charges(self):
    """Create subscription charges for devices whose MRF is due."""
    client_ip = getattr(settings, "SUBSCRIPTION_BILLING_CLIENT_IP", "") or ""
    charges = services.process_due_subscriptions(client_ip=client_ip)
    if charges:
        logger.info("Generated %s subscription charges", len(charges))
    return [charge.pk for charge in charges]


@shared_task(bind=True, name="subscriptions.suspend_overdue_subscriptions")
def suspend_overdue_subscriptions(self):
    """Move subscriptions out of grace once the deadline passes."""
    updated = services.suspend_overdue_subscriptions()
    if updated:
        logger.info("Suspended %s overdue subscriptions", updated)
    return updated


@shared_task(bind=True, name="subscriptions.refresh_subscription_statuses")
def refresh_subscription_statuses(self):
    """Best-effort reconciliation to keep GRACE/SUSPENDED states accurate."""
    now = timezone.now()
    count = 0
    qs = DeviceSubscription.objects.filter(
        status__in=[
            DeviceSubscription.Status.GRACE,
            DeviceSubscription.Status.SUSPENDED,
        ]
    ).only("id")
    for sub in qs.iterator():
        services.refresh_subscription_status(sub, now=now)
        count += 1
    if count:
        logger.info("Refreshed %s subscription records", count)
    return count


@shared_task(bind=True, name="subscriptions.send_due_soon_reminders")
def send_due_soon_reminders(self, days_before: int = 5):
    """Send SMS reminders ahead of subscription due dates."""

    sent = services.send_due_soon_sms_reminders(days_before=days_before)
    if sent:
        logger.info("Sent %s due soon subscription reminders", sent)
    return sent
