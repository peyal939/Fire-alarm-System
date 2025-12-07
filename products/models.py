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


class OrderFulfillment(AuditSoftDeleteModel):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="fulfillments"
    )
    hardware_identifier = models.CharField(max_length=64, unique=True)
    device_role = models.CharField(
        max_length=10,
        choices=[("master", "Master"), ("slave", "Slave")],
        default="master",
    )
    master_hardware_identifier = models.CharField(max_length=64, null=True, blank=True)
    is_claimed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["hardware_identifier"]),
            models.Index(fields=["order", "is_claimed"]),
        ]

    def __str__(self) -> str:
        return f"{self.hardware_identifier} ({self.device_role})"


class Cart(models.Model):
    """Shopping cart for users to collect packages before checkout."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
    )
    expires_at = models.DateTimeField(
        help_text="Cart auto-expires after 7 days of inactivity",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Cart for {self.user_id}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def refresh_expiry(self, days: int = 7) -> None:
        """Extend cart expiry by specified days from now."""
        self.expires_at = timezone.now() + timezone.timedelta(days=days)
        self.save(update_fields=["expires_at", "updated_at"])

    def get_total(self):
        """Calculate total cart value."""
        from decimal import Decimal
        total = Decimal("0.00")
        for item in self.items.select_related("package"):
            price = item.package.price_per_device or Decimal("0")
            mrf = item.package.mrf or Decimal("0")
            total += (price + mrf) * item.quantity
        return total


class CartItem(models.Model):
    """Individual item in a shopping cart."""

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(default=1)
    number_of_master_devices = models.PositiveIntegerField(default=1)
    number_of_slave_devices = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("cart", "package")
        indexes = [
            models.Index(fields=["cart", "package"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.quantity}x {self.package.name} in cart {self.cart_id}"

    @property
    def line_total(self):
        """Calculate total for this line item."""
        from decimal import Decimal
        price = self.package.price_per_device or Decimal("0")
        mrf = self.package.mrf or Decimal("0")
        return (price + mrf) * self.quantity
