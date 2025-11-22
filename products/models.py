from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .enums import OrderStatus


class AuditSoftDeleteModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by",
    )
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_deleted_by",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_updated_by",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Package(AuditSoftDeleteModel):
    name = models.CharField(max_length=64, unique=True)
    min_quantity = models.PositiveIntegerField(default=1)
    max_quantity = models.PositiveIntegerField()
    price_per_device = models.DecimalField(max_digits=10, decimal_places=2)
    mrf = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Monthly recurring fee (MRF) for this package",
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Order(AuditSoftDeleteModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders"
    )
    package = models.ForeignKey(
        Package, on_delete=models.PROTECT, related_name="orders"
    )
    number_of_master_devices = models.PositiveIntegerField(default=1)
    number_of_slave_devices = models.PositiveIntegerField(default=0)
    quantity = models.PositiveIntegerField()
    # renamed from total_amount -> amount
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # external/payment provider reference (e.g. SurjoPay order id)
    reference = models.CharField(max_length=128, blank=True)

    # currency and customer details
    currency = models.CharField(max_length=8, default="BDT")
    customer_name = models.CharField(max_length=128, blank=True)
    customer_address = models.TextField(blank=True)
    customer_phone = models.CharField(max_length=32, blank=True)
    customer_city = models.CharField(max_length=64, blank=True)
    customer_post_code = models.CharField(max_length=32, blank=True)
    customer_email = models.CharField(max_length=254, blank=True)
    order_status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.PENDING
    )
    gateway_transaction_id = models.CharField(max_length=128, blank=True)
    gateway_response = models.JSONField(null=True, blank=True)
    shipping_address = models.TextField(blank=True)
    ordered_at = models.DateTimeField(default=timezone.now, db_index=True)
    assigned_devices = models.PositiveIntegerField(
        default=0,
        help_text="Number of device registrations already linked to this order",
    )

    class Meta:
        ordering = ["-ordered_at"]
        indexes = [
            models.Index(fields=["user", "ordered_at"]),
            models.Index(fields=["package", "ordered_at"]),
            models.Index(fields=["assigned_devices"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Order {self.pk} ({self.order_status})"

    @property
    def remaining_device_slots(self) -> int:
        """Return how many device registrations can still be linked to this order."""
        remaining = (self.quantity or 0) - (self.assigned_devices or 0)
        return remaining if remaining > 0 else 0
