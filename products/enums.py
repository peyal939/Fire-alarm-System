from django.db import models


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    CANCELLED = "cancelled", "Cancelled"
    FAILED = "failed", "Failed"
    DELIVERED = "delivered", "Delivered"
    PROCESSING = "processing", "Processing"
    SHIPPED = "shipped", "Shipped"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_FULFILLED = "partial", "Partially Fulfilled"
