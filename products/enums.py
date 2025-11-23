from django.db import models


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    CANCELLED = "cancelled", "Cancelled"
    FAILED = "failed", "Failed"
    DELIVERED = "delivered", "Delivered"
