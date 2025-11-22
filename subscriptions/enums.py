from django.db import models


class DeviceSubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    GRACE = "grace", "Grace"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"


class SubscriptionChargeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
