from __future__ import annotations

from django.dispatch import Signal, receiver
from django.db import transaction
from typing import Optional

from .enums import OrderStatus
from .models import Order

# Signal fired when external payment notification is received.
# payload: provider_order_id (str), transaction_id (str|None), gateway_response (dict|None)
payment_received = Signal()


@receiver(payment_received)
def handle_payment_received(
    sender,
    provider_order_id: str,
    transaction_id: Optional[str] = None,
    gateway_response=None,
    **kwargs,
):
    """
    Find pending orders matching the incoming provider_order_id.
    Matching strategy:
      - Orders with reference == provider_order_id
      - If provider_order_id is numeric, also try matching Order.id

    For each matched pending order: mark as paid, set gateway fields.
    """
    if not provider_order_id:
        return
    with transaction.atomic():
        qs = Order.objects.select_for_update().filter(
            deleted_at__isnull=True, order_status=OrderStatus.PENDING
        )
        # match by reference
        matches = qs.filter(reference=provider_order_id)
        # if provider id looks like an integer, also try matching by Order.id
        try:
            numeric = int(provider_order_id)
        except Exception:
            numeric = None
        if numeric is not None:
            matches = matches | qs.filter(id=numeric)
        # iterate and update matched pending orders
        for order in matches.distinct():
            order.order_status = OrderStatus.PAID
            if transaction_id:
                order.gateway_transaction_id = transaction_id
            if gateway_response is not None:
                order.gateway_response = gateway_response
            order.save(
                update_fields=[
                    "order_status",
                    "gateway_transaction_id",
                    "gateway_response",
                ]
            )
