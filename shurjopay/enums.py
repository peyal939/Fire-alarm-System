from django.db import models


class PaymentTransactionStatus(models.TextChoices):
    CREATED = "created", "Created"
    INITIATED = "initiated", "Initiated"
    REDIRECTED = "redirected", "Redirected"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
