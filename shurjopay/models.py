from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .enums import PaymentTransactionStatus


class PaymentTransaction(models.Model):
    """Minimal record linking our domain (user/order) to shurjoPay.

    This model is intentionally generic so the products app can reference it
    by FK or store the ID in its own tables. It captures the flow:
    - created -> initiated -> redirected -> verified_(success|failed|cancelled)
    """

    # Optional linkage to a user; products app can use its own linkage
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    # Optional linkage to a domain object (e.g., Order ID from products app)
    reference = models.CharField(
        max_length=128, blank=True, help_text="Domain reference (e.g., Order ID)"
    )

    # Request/response fields
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="BDT")

    # shurjoPay identifiers
    sp_order_id = models.CharField(max_length=128, blank=True, db_index=True)
    customer_order_id = models.CharField(max_length=128, blank=True)

    # URLs for redirection
    checkout_url = models.TextField(blank=True)

    status = models.CharField(
        max_length=16,
        choices=PaymentTransactionStatus,
        default=PaymentTransactionStatus.CREATED,
        db_index=True,
    )

    # Audit
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Raw payloads for troubleshooting
    request_payload = models.JSONField(null=True, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    verification_payload = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:  # pragma: no cover
        base = self.customer_order_id or self.reference or str(self.pk)
        return f"Payment {base} [{self.status}]"
