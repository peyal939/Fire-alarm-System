from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from .enums import DeviceSubscriptionStatus, SubscriptionChargeStatus


class DeviceSubscription(models.Model):
    device = models.OneToOneField(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    originating_order = models.ForeignKey(
        "products.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subscriptions",
    )
    monthly_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    status = models.CharField(
        max_length=16,
        choices=DeviceSubscriptionStatus,
        default=DeviceSubscriptionStatus.ACTIVE,
    )
    billing_anchor = models.DateTimeField()
    last_paid_through = models.DateTimeField()
    next_due_at = models.DateTimeField()
    grace_expires_at = models.DateTimeField(null=True, blank=True)
    admin_override_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["next_due_at"]),
            models.Index(fields=["grace_expires_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Subscription for {self.device_id} ({self.status})"

    @property
    def is_active_for_user(self) -> bool:
        if self.status == DeviceSubscriptionStatus.ACTIVE:
            return True
        now = timezone.now()
        if self.status == DeviceSubscriptionStatus.GRACE and (
            not self.grace_expires_at or self.grace_expires_at >= now
        ):
            return True
        if self.admin_override_until and self.admin_override_until >= now:
            return True
        return False


class SubscriptionCharge(models.Model):
    subscription = models.ForeignKey(
        DeviceSubscription,
        on_delete=models.CASCADE,
        related_name="charges",
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    cycles = models.PositiveSmallIntegerField(
        default=1,
        help_text="Number of billing cycles covered by this charge",
    )
    status = models.CharField(
        max_length=16,
        choices=SubscriptionChargeStatus,
        default=SubscriptionChargeStatus.PENDING,
    )
    provider_reference = models.CharField(max_length=191, blank=True)
    payment_transaction = models.ForeignKey(
        "shurjopay.PaymentTransaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subscription_charges",
    )
    payload_snapshot = models.JSONField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    is_manual = models.BooleanField(default=False)
    manual_notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="manual_subscription_charges",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("subscription", "period_start", "period_end")
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["period_end"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Charge {self.pk} ({self.status})"
