from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from shurjopay import services as shurjopay_services
from shurjopay.enums import PaymentTransactionStatus
from shurjopay.models import PaymentTransaction

from .enums import OrderStatus, PaymentMethod
from .models import Order, OrderFulfillment
from devices.models import Device

logger = logging.getLogger(__name__)


def calculate_order_total(package, quantity, number_of_master_devices=None) -> Decimal:
    """Return the upfront order total including device and MRF charges.
    
    MRF is only charged for master devices, not slaves.
    """
    if not package or quantity is None:
        return Decimal("0")
    try:
        qty = Decimal(quantity)
    except Exception:  # pragma: no cover - invalid input fallback
        qty = Decimal("0")
    
    # If number_of_master_devices not provided, default to quantity (legacy behavior)
    if number_of_master_devices is None:
        master_qty = qty
    else:
        try:
            master_qty = Decimal(number_of_master_devices)
        except Exception:
            master_qty = qty
    
    price_per_device = getattr(package, "price_per_device", Decimal("0")) or Decimal("0")
    mrf = getattr(package, "mrf", Decimal("0")) or Decimal("0")
    # Device price for all, MRF only for masters
    return (price_per_device * qty) + (mrf * master_qty)


def _build_reference(order: Order) -> str:
    return f"order:{order.pk}"


def _coerce_payload(payload: Any) -> Any:
    if payload is None:
        return None
    try:
        return json.loads(json.dumps(payload, default=str))
    except Exception:  # pragma: no cover - best effort sanitisation
        return payload


def _customer_payload(order: Order) -> dict:
    user = getattr(order, "user", None)
    payload = {
        "customer_name": (order.customer_name or "").strip() or getattr(user, "full_name", ""),
        "customer_address": (order.customer_address or "").strip() or getattr(user, "address", ""),
        "customer_phone": (order.customer_phone or "").strip() or getattr(user, "phone_number", ""),
        "customer_city": (order.customer_city or "").strip(),
        "customer_post_code": (order.customer_post_code or "").strip(),
        "customer_email": (order.customer_email or "").strip() or getattr(user, "email", ""),
    }
    defaults = {
        "customer_name": "Fire Alarm Customer",
        "customer_address": "Dhaka",
        "customer_phone": "+8801000000000",
        "customer_city": "Dhaka",
        "customer_post_code": "1000",
        "customer_email": "no-reply@pranisheba.com",
    }
    for key, default in defaults.items():
        value = (payload.get(key) or "").strip()
        payload[key] = value if value else default
    return payload


def initiate_payment_for_order(
    order: Order,
    *,
    client_ip: str = "",
    actor=None,
) -> Optional[PaymentTransaction]:
    """Create a shurjoPay transaction for the order and return the PaymentTransaction."""

    if not order or not getattr(order, "pk", None):
        logger.warning("Cannot initiate payment without a persisted order instance")
        return None

    if getattr(order, "payment_method", PaymentMethod.ONLINE) != PaymentMethod.ONLINE:
        logger.info(
            "Skipping payment initiation for non-online method: order %s uses %s",
            getattr(order, "pk", None),
            getattr(order, "payment_method", None),
        )
        return None

    with transaction.atomic():
        order_locked = (
            Order.objects.select_for_update()
            .select_related("user", "package")
            .get(pk=order.pk)
        )
        if order_locked.order_status == OrderStatus.PAID:
            logger.info("Order %s already paid; skipping payment initiation", order_locked.pk)
            return None
        amount = order_locked.amount or Decimal("0")
        if amount <= 0:
            logger.warning("Order %s has non-positive amount %s", order_locked.pk, amount)
            return None
        currency = (order_locked.currency or "BDT").strip() or "BDT"
        customer = _customer_payload(order_locked)
        txn = PaymentTransaction.objects.create(
            user=order_locked.user,
            reference=_build_reference(order_locked),
            amount=amount,
            currency=currency,
            status=PaymentTransactionStatus.INITIATED,
            request_payload={
                "order_id": order_locked.pk,
                "client_ip": client_ip,
                "customer": customer,
            },
        )
        order_id = order_locked.pk

    try:
        details = shurjopay_services.initiate_payment(
            amount=float(amount),
            order_id=f"ORD-{order_id}-{txn.pk}",
            currency=currency,
            client_ip=client_ip,
            **customer,
        )
    except Exception:  # pragma: no cover - upstream failure
        logger.exception("shurjoPay initiation failed for order %s", order_id)
        details = None

    if not details:
        txn.status = PaymentTransactionStatus.FAILED
        txn.save(update_fields=["status", "updated_at"])
        _record_gateway_state(order_id, None, {"error": "initiate_failed"}, actor)
        return None

    txn.checkout_url = getattr(details, "checkout_url", "")
    txn.sp_order_id = getattr(details, "sp_order_id", "")
    txn.customer_order_id = getattr(details, "customer_order_id", f"ORD-{order_id}-{txn.pk}")
    has_checkout = bool(txn.checkout_url)
    txn.status = (
        PaymentTransactionStatus.REDIRECTED
        if has_checkout
        else PaymentTransactionStatus.FAILED
    )
    txn.response_payload = getattr(details, "__dict__", None)
    txn.save()

    provider_ref = txn.sp_order_id or txn.customer_order_id or str(txn.pk)
    payload = _coerce_payload(txn.response_payload)
    _record_gateway_state(order_id, provider_ref, payload, actor)
    if not has_checkout:
        logger.warning(
            "shurjoPay did not return checkout URL for order %s (transaction %s)",
            order_id,
            txn.pk,
        )
        return None
    return txn


def _record_gateway_state(order_id: int, provider_ref: Optional[str], payload: Any, actor=None) -> None:
    with transaction.atomic():
        try:
            order_locked = Order.objects.select_for_update().get(pk=order_id)
        except Order.DoesNotExist:
            logger.warning("Order %s missing when recording gateway state", order_id)
            return
        updates: list[str] = []
        if provider_ref and order_locked.gateway_transaction_id != provider_ref:
            order_locked.gateway_transaction_id = provider_ref
            updates.append("gateway_transaction_id")
        if payload is not None:
            order_locked.gateway_response = payload
            if "gateway_response" not in updates:
                updates.append("gateway_response")
        if actor and getattr(actor, "pk", None):
            order_locked.updated_by = actor
            if "updated_by" not in updates:
                updates.append("updated_by")
        if updates:
            if "updated_at" not in updates:
                order_locked.updated_at = timezone.now()
                updates.append("updated_at")
            order_locked.save(update_fields=updates)


def _extract_order_id(transaction_obj: PaymentTransaction) -> Optional[int]:
    if not transaction_obj:
        return None
    reference = transaction_obj.reference or ""
    if reference.startswith("order:"):
        try:
            return int(reference.split(":", 1)[1])
        except (TypeError, ValueError):
            return None
    payload = transaction_obj.request_payload or {}
    try:
        return int(payload.get("order_id")) if payload and payload.get("order_id") else None
    except (TypeError, ValueError):
        return None


def sync_order_from_transaction(transaction_obj: PaymentTransaction) -> Optional[Order]:
    """Apply the latest payment transaction status to the related order."""

    order_id = _extract_order_id(transaction_obj)
    if not order_id:
        return None

    with transaction.atomic():
        try:
            order_locked = (
                Order.objects.select_for_update()
                .select_related("user")
                .get(pk=order_id)
            )
        except Order.DoesNotExist:
            logger.warning(
                "Payment transaction %s references missing order %s",
                getattr(transaction_obj, "pk", None),
                order_id,
            )
            return None

        updates: list[str] = []
        provider_ref = (
            transaction_obj.sp_order_id
            or transaction_obj.customer_order_id
            or order_locked.gateway_transaction_id
        )
        if provider_ref and order_locked.gateway_transaction_id != provider_ref:
            order_locked.gateway_transaction_id = provider_ref
            updates.append("gateway_transaction_id")

        payload = transaction_obj.verification_payload or transaction_obj.response_payload
        coerced_payload = _coerce_payload(payload)
        if coerced_payload is not None:
            order_locked.gateway_response = coerced_payload
            if "gateway_response" not in updates:
                updates.append("gateway_response")

        if transaction_obj.status == PaymentTransactionStatus.SUCCESS:
            if order_locked.order_status != OrderStatus.PAID:
                order_locked.order_status = OrderStatus.PAID
                updates.append("order_status")
        if transaction_obj.user and getattr(transaction_obj.user, "pk", None):
            order_locked.updated_by = transaction_obj.user
            if "updated_by" not in updates:
                updates.append("updated_by")

        if updates:
            if "updated_at" not in updates:
                order_locked.updated_at = timezone.now()
                updates.append("updated_at")
            order_locked.save(update_fields=updates)
        return order_locked


def fulfill_order(order: Order, master_ids: list[str], slave_data: list[dict], actor=None) -> None:
    """
    Assign specific hardware identifiers to an order.
    Creates Device records for the user.
    slave_data: list of dicts {'id': '...', 'master_id': '...'}
    """
    if not order:
        raise ValidationError("Order is required")

    # Check if order is already fulfilled
    required_total = order.number_of_master_devices + order.number_of_slave_devices
    if order.assigned_devices >= required_total:
        raise ValidationError("Order is already fulfilled.")

    if len(master_ids) != order.number_of_master_devices:
        raise ValidationError(f"Expected {order.number_of_master_devices} master IDs, got {len(master_ids)}")
    
    if len(slave_data) != order.number_of_slave_devices:
        raise ValidationError(f"Expected {order.number_of_slave_devices} slave IDs, got {len(slave_data)}")

    slave_ids = [s['id'] for s in slave_data]

    # Check for duplicates in input
    all_ids = master_ids + slave_ids
    if len(all_ids) != len(set(all_ids)):
        raise ValidationError("Duplicate hardware identifiers provided")

    # Check if any ID is already registered/assigned (active devices)
    existing = Device.objects.filter(hardware_identifier__in=all_ids, deleted_at__isnull=True)
    if existing.exists():
        found = ", ".join([d.hardware_identifier for d in existing])
        raise ValidationError(f"The following devices are already registered: {found}")

    # Check if any ID is already fulfilled (OrderFulfillment)
    existing_fulfillment = OrderFulfillment.objects.filter(hardware_identifier__in=all_ids, deleted_at__isnull=True)
    if existing_fulfillment.exists():
        found = ", ".join([f.hardware_identifier for f in existing_fulfillment])
        raise ValidationError(f"The following devices are already fulfilled: {found}")

    with transaction.atomic():
        # Create Masters
        for hid in master_ids:
            OrderFulfillment.objects.create(
                order=order,
                hardware_identifier=hid,
                device_role="master",
                created_by=actor,
            )
        
        # Create Slaves
        for item in slave_data:
            hid = item['id']
            master_hid = item.get('master_id')
            
            OrderFulfillment.objects.create(
                order=order,
                hardware_identifier=hid,
                device_role="slave",
                master_hardware_identifier=master_hid,
                created_by=actor,
            )
        
        # Update order assigned count
        order.assigned_devices = len(all_ids)
        order.save(update_fields=["assigned_devices"])

