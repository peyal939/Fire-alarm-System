from django.db import models


class NotificationStatus(models.TextChoices):
    SENT = "sent", "Sent Successfully"
    FAILED = "failed", "Failed"
    INVALID_TOKEN = "invalid_token", "Invalid Token"
