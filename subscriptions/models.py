from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from .enums import DeviceSubscriptionStatus, SubscriptionChargeStatus, InvoiceStatus


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
    due_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    due_reminder_for_due_at = models.DateTimeField(null=True, blank=True)
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
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of manual payment retry attempts",
    )
    last_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of last manual retry attempt",
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


class Invoice(models.Model):
    """Invoice generated for orders or subscription charges."""

    number = models.CharField(
        max_length=32,
        unique=True,
        help_text="Invoice number, e.g., INV-2025-000001",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    order = models.ForeignKey(
        "products.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    subscription_charge = models.ForeignKey(
        SubscriptionCharge,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=16,
        choices=InvoiceStatus,
        default=InvoiceStatus.DRAFT,
    )
    pdf_file = models.FileField(
        upload_to="invoices/",
        null=True,
        blank=True,
        help_text="Generated PDF invoice file",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["number"]),
            models.Index(fields=["issued_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Invoice {self.number} ({self.status})"

    @classmethod
    def generate_invoice_number(cls) -> str:
        """Generate a unique invoice number like INV-2025-000001."""
        from django.db.models import Max
        year = timezone.now().year
        prefix = f"INV-{year}-"
        last_invoice = cls.objects.filter(number__startswith=prefix).aggregate(
            max_num=Max("number")
        )
        if last_invoice["max_num"]:
            try:
                last_seq = int(last_invoice["max_num"].split("-")[-1])
            except (ValueError, IndexError):
                last_seq = 0
        else:
            last_seq = 0
        new_seq = last_seq + 1
        return f"{prefix}{new_seq:06d}"


class InvoiceLineItem(models.Model):
    """Individual line item on an invoice."""

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.description} ({self.quantity}x)"

    def save(self, *args, **kwargs):
        # Auto-calculate total if not set
        if not self.total:
            self.total = self.unit_price * self.quantity
        super().save(*args, **kwargs)
