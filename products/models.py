from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


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

    class Meta:
        abstract = True


class Package(AuditSoftDeleteModel):
    name = models.CharField(max_length=64, unique=True)
    min_quantity = models.PositiveIntegerField(default=1)
    max_quantity = models.PositiveIntegerField()
    price_per_device = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Order(AuditSoftDeleteModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders"
    )
    package = models.ForeignKey(
        Package, on_delete=models.PROTECT, related_name="orders"
    )
    quantity = models.PositiveIntegerField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    order_status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    gateway_transaction_id = models.CharField(max_length=128, blank=True)
    gateway_response = models.JSONField(null=True, blank=True)
    shipping_address = models.TextField(blank=True)
    ordered_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-ordered_at"]
        indexes = [
            models.Index(fields=["user", "ordered_at"]),
            models.Index(fields=["package", "ordered_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Order {self.pk} ({self.order_status})"
