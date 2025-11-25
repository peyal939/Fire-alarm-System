from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import logging
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from shurjopay import services as shurjopay_services
from shurjopay.enums import PaymentTransactionStatus
from shurjopay.models import PaymentTransaction

from notifications.sms import SMSClient
from .enums import DeviceSubscriptionStatus, SubscriptionChargeStatus
from .models import DeviceSubscription, SubscriptionCharge


logger = logging.getLogger(__name__)


def _cycle_delta() -> timedelta:
    days_raw = getattr(settings, "SUBSCRIPTION_CYCLE_DAYS", 30) or 30
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        days = 30
    days = max(days, 1)
    return timedelta(days=days)


def _grace_delta() -> timedelta:
    days_raw = getattr(settings, "SUBSCRIPTION_GRACE_DAYS", 7)
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        days = 7
    days = max(days, 0)
    return timedelta(days=days)


def _build_subscription_reference(charge_id: int) -> str:
    return f"subscription:{charge_id}"


def ensure_device_subscription(
    device, *, activation_time=None
) -> Optional[DeviceSubscription]:
    """Create or update a subscription for the given device."""

    if not device or not getattr(device, "pk", None):
        return None

    if activation_time is None:
        activation_time = getattr(device, "registered_at", None) or timezone.now()

    monthly_amount = Decimal("0.00")
    originating_order = getattr(device, "originating_order", None)
    if originating_order and getattr(originating_order, "package", None):
        monthly_amount = originating_order.package.mrf or Decimal("0.00")

    # Default to 30-day coverage for the first prepaid month
    first_cycle_end = activation_time + timedelta(days=30)

    with transaction.atomic():
        (
            subscription,
            created,
        ) = DeviceSubscription.objects.select_for_update().get_or_create(
            device=device,
            defaults={
                "originating_order": originating_order,
                "monthly_amount": monthly_amount,
                "status": DeviceSubscriptionStatus.ACTIVE,
                "billing_anchor": activation_time,
                "last_paid_through": first_cycle_end,
                "next_due_at": first_cycle_end,
            },
        )

        if created:
            return subscription

        fields_to_update = []
        if (
            originating_order
            and subscription.originating_order_id != originating_order.id
        ):
            subscription.originating_order = originating_order
            fields_to_update.append("originating_order")
        if monthly_amount and subscription.monthly_amount != monthly_amount:
            subscription.monthly_amount = monthly_amount
            fields_to_update.append("monthly_amount")
        if not subscription.billing_anchor:
            subscription.billing_anchor = activation_time
            fields_to_update.append("billing_anchor")
        if not subscription.last_paid_through:
            subscription.last_paid_through = first_cycle_end
            subscription.next_due_at = first_cycle_end
            fields_to_update.extend(["last_paid_through", "next_due_at"])

        if fields_to_update:
            subscription.save(update_fields=fields_to_update)
        return subscription


def _determine_period_range(
    subscription: DeviceSubscription,
    *,
    cycles: int = 1,
    anchor: Optional[timezone.datetime] = None,
) -> tuple[timezone.datetime, timezone.datetime]:
    start = (
        anchor
        or subscription.last_paid_through
        or subscription.billing_anchor
        or timezone.now()
    )
    cycles = max(1, int(cycles or 1))
    end = start + (_cycle_delta() * cycles)
    return start, end


def _customer_payload(subscription: DeviceSubscription) -> dict:
    device = getattr(subscription, "device", None)
    order = getattr(subscription, "originating_order", None)
    user = getattr(device, "user", None)
    payload = {
        "customer_name": (order.customer_name if order else None)
        or (getattr(user, "full_name", None) or "")
        or (getattr(user, "email", "") or ""),
        "customer_address": (order.customer_address if order else None)
        or getattr(user, "address", ""),
        "customer_phone": (order.customer_phone if order else None)
        or getattr(user, "phone_number", ""),
        "customer_city": (order.customer_city if order else None) or "",
        "customer_post_code": (order.customer_post_code if order else None) or "",
        "customer_email": (order.customer_email if order else None)
        or getattr(user, "email", ""),
    }
    defaults = {
        "customer_name": "Fire Alarm Subscriber",
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


def create_charge_for_subscription(
    subscription: DeviceSubscription,
    *,
    as_of: Optional[timezone.datetime] = None,
    auto_initiate: bool = True,
    client_ip: str = "",
    cycles: int = 1,
    allow_prepay: bool = False,
) -> Optional[SubscriptionCharge]:
    """Create a charge covering one or more billing cycles."""

    as_of = as_of or timezone.now()
    if not subscription or not getattr(subscription, "pk", None):
        return None
    if subscription.monthly_amount <= 0:
        return None
    if (
        subscription.next_due_at
        and subscription.next_due_at > as_of
        and not allow_prepay
    ):
        return None

    with transaction.atomic():
        sub = (
            DeviceSubscription.objects.select_for_update()
            .select_related("device", "originating_order")
            .get(pk=subscription.pk)
        )
        if sub.monthly_amount <= 0:
            return None
        if sub.next_due_at and sub.next_due_at > as_of and not allow_prepay:
            return sub.charges.order_by("-period_end").first()

        cycles = max(1, int(cycles or 1))
        period_start = sub.last_paid_through or sub.billing_anchor or as_of
        if allow_prepay and sub.next_due_at and sub.next_due_at > as_of:
            period_start = sub.next_due_at
        period_start = period_start or as_of
        period_end = period_start + (_cycle_delta() * cycles)

        charge, created = SubscriptionCharge.objects.get_or_create(
            subscription=sub,
            period_start=period_start,
            period_end=period_end,
            defaults={
                "amount": sub.monthly_amount * cycles,
                "cycles": cycles,
            },
        )

        if not created:
            desired_amount = sub.monthly_amount * cycles
            updates: list[str] = []
            if charge.amount != desired_amount:
                charge.amount = desired_amount
                updates.append("amount")
            if charge.cycles != cycles:
                charge.cycles = cycles
                updates.append("cycles")
            if updates:
                charge.save(update_fields=updates)

        if created:
            updates: list[str] = []
            if period_start <= as_of:
                sub.status = DeviceSubscriptionStatus.GRACE
                sub.grace_expires_at = period_start + _grace_delta()
                updates.extend(["status", "grace_expires_at"])
            if updates:
                sub.save(update_fields=updates)

        # Initiate payment outside select_for_update block to avoid long locks
    if auto_initiate and charge and not charge.payment_transaction:
        try:
            initiate_payment_for_charge(charge, client_ip=client_ip)
        except Exception:
            logger.exception("Failed to initiate payment for charge %s", charge.pk)
    return charge


def initiate_payment_for_charge(
    charge: SubscriptionCharge,
    *,
    client_ip: str = "",
) -> Optional[PaymentTransaction]:
    if not charge or not getattr(charge, "pk", None):
        return None
    subscription = charge.subscription
    device = getattr(subscription, "device", None)
    user = getattr(device, "user", None)
    if not user:
        logger.warning("Charge %s missing user context", charge.pk)
        return None

    currency = "BDT"
    if subscription.originating_order and subscription.originating_order.currency:
        currency = subscription.originating_order.currency
    order_id = f"SUB-{charge.pk}"
    customer_payload = _customer_payload(subscription)

    with transaction.atomic():
        txn = PaymentTransaction.objects.create(
            user=user,
            reference=_build_subscription_reference(charge.pk),
            amount=charge.amount,
            currency=currency,
            status=PaymentTransactionStatus.INITIATED,
            request_payload={
                "subscription_id": subscription.pk,
                "charge_id": charge.pk,
                "client_ip": client_ip,
                "customer": customer_payload,
            },
        )

    details = shurjopay_services.initiate_payment(
        amount=float(charge.amount),
        order_id=order_id,
        currency=currency,
        client_ip=client_ip,
        **customer_payload,
    )

    if not details:
        txn.status = PaymentTransactionStatus.FAILED
        txn.save(update_fields=["status"])
        charge.status = SubscriptionChargeStatus.FAILED
        charge.failure_reason = "Unable to initiate payment with shurjoPay"
        charge.save(update_fields=["status", "failure_reason"])
        return None

    txn.checkout_url = getattr(details, "checkout_url", "")
    txn.sp_order_id = getattr(details, "sp_order_id", "")
    txn.customer_order_id = getattr(details, "customer_order_id", order_id)
    txn.status = (
        PaymentTransactionStatus.REDIRECTED
        if txn.checkout_url
        else PaymentTransactionStatus.INITIATED
    )
    txn.response_payload = getattr(details, "__dict__", None)
    txn.save()

    charge.payment_transaction = txn
    charge.provider_reference = txn.sp_order_id or txn.customer_order_id
    charge.payload_snapshot = {
        "auto_client_ip": client_ip,
        "customer": customer_payload,
        "order_id": order_id,
    }
    charge.save(
        update_fields=["payment_transaction", "provider_reference", "payload_snapshot"]
    )
    return txn


def process_due_subscriptions(
    *,
    limit: int = 50,
    as_of: Optional[timezone.datetime] = None,
    client_ip: str = "",
) -> list[SubscriptionCharge]:
    now = as_of or timezone.now()
    qs = (
        DeviceSubscription.objects.filter(
            monthly_amount__gt=0,
            next_due_at__lte=now,
            device__deleted_at__isnull=True,
        )
        .exclude(status=DeviceSubscriptionStatus.CANCELLED)
        .select_related("device", "originating_order")
        .order_by("next_due_at")
    )
    charges: list[SubscriptionCharge] = []
    for sub in qs[:limit]:
        charge = create_charge_for_subscription(
            sub, as_of=now, auto_initiate=True, client_ip=client_ip
        )
        if charge:
            charges.append(charge)
    return charges


def apply_manual_payment(
    subscription: DeviceSubscription,
    *,
    months: int,
    note: str = "",
    actor=None,
) -> Optional[SubscriptionCharge]:
    months = max(1, int(months or 1))
    if not subscription or not getattr(subscription, "pk", None):
        return None
    with transaction.atomic():
        sub = (
            DeviceSubscription.objects.select_for_update()
            .select_related("device")
            .get(pk=subscription.pk)
        )
        period_start = sub.last_paid_through or sub.billing_anchor or timezone.now()
        period_end = period_start + (_cycle_delta() * months)
        charge = SubscriptionCharge.objects.create(
            subscription=sub,
            period_start=period_start,
            period_end=period_end,
            amount=sub.monthly_amount * months,
            status=SubscriptionChargeStatus.PAID,
            provider_reference="manual-cash",
            cycles=months,
            is_manual=True,
            manual_notes=note,
            recorded_by=actor if actor and getattr(actor, "pk", None) else None,
        )

        pending_qs = sub.charges.filter(
            status=SubscriptionChargeStatus.PENDING
        ).exclude(pk=charge.pk)
        if pending_qs.exists():
            pending_qs.update(
                status=SubscriptionChargeStatus.CANCELLED,
                failure_reason=(
                    f"Superseded by manual payment on {timezone.now():%Y-%m-%d}"
                ),
            )

        sub.last_paid_through = period_end
        sub.next_due_at = period_end
        sub.grace_expires_at = None
        sub.status = DeviceSubscriptionStatus.ACTIVE
        sub.save(
            update_fields=[
                "last_paid_through",
                "next_due_at",
                "grace_expires_at",
                "status",
            ]
        )
        return charge


def refresh_subscription_status(
    subscription: DeviceSubscription, *, now: Optional[timezone.datetime] = None
) -> DeviceSubscription:
    now = now or timezone.now()
    if not subscription or not getattr(subscription, "pk", None):
        return subscription

    with transaction.atomic():
        sub = DeviceSubscription.objects.select_for_update().get(pk=subscription.pk)
        has_pending = sub.charges.filter(
            status=SubscriptionChargeStatus.PENDING
        ).exists()
        new_status = sub.status
        fields: list[str] = []
        if has_pending:
            expired = sub.grace_expires_at and sub.grace_expires_at < now
            new_status = (
                DeviceSubscriptionStatus.SUSPENDED
                if expired
                else DeviceSubscriptionStatus.GRACE
            )
        else:
            new_status = DeviceSubscriptionStatus.ACTIVE
            if sub.grace_expires_at is not None:
                sub.grace_expires_at = None
                fields.append("grace_expires_at")

        if sub.status != new_status:
            sub.status = new_status
            fields.append("status")
        if fields:
            sub.save(update_fields=fields)
        return sub


def suspend_overdue_subscriptions(now: Optional[timezone.datetime] = None) -> int:
    now = now or timezone.now()
    qs = DeviceSubscription.objects.filter(
        status=DeviceSubscriptionStatus.GRACE,
        grace_expires_at__lt=now,
        charges__status=SubscriptionChargeStatus.PENDING,
    )
    updated = qs.update(status=DeviceSubscriptionStatus.SUSPENDED)
    return updated


def _extract_charge_id_from_reference(reference: str) -> Optional[int]:
    if not reference or "subscription:" not in reference:
        return None
    try:
        return int(reference.split(":")[-1])
    except (TypeError, ValueError):
        return None


def sync_charge_from_transaction(
    transaction_obj: PaymentTransaction,
) -> Optional[SubscriptionCharge]:
    if not transaction_obj:
        return None
    charge = (
        SubscriptionCharge.objects.select_related("subscription")
        .filter(payment_transaction=transaction_obj)
        .first()
    )
    if not charge and transaction_obj.reference:
        charge_id = _extract_charge_id_from_reference(transaction_obj.reference)
        if charge_id:
            charge = SubscriptionCharge.objects.filter(pk=charge_id).first()
    if not charge:
        return None

    with transaction.atomic():
        charge = (
            SubscriptionCharge.objects.select_for_update()
            .select_related("subscription")
            .get(pk=charge.pk)
        )
        subscription = charge.subscription
        status = transaction_obj.status

        provider_ref = (
            transaction_obj.sp_order_id
            or transaction_obj.customer_order_id
            or charge.provider_reference
        )

        if status == PaymentTransactionStatus.SUCCESS:
            if charge.status != SubscriptionChargeStatus.PAID:
                charge.status = SubscriptionChargeStatus.PAID
                charge.failure_reason = ""
                charge.provider_reference = provider_ref
                charge.save(
                    update_fields=["status", "failure_reason", "provider_reference"]
                )
                subscription.last_paid_through = charge.period_end
                subscription.next_due_at = charge.period_end
                subscription.grace_expires_at = None
                subscription.status = DeviceSubscriptionStatus.ACTIVE
                subscription.save(
                    update_fields=[
                        "last_paid_through",
                        "next_due_at",
                        "grace_expires_at",
                        "status",
                    ]
                )
            return charge

        if status == PaymentTransactionStatus.CANCELLED:
            if charge.status != SubscriptionChargeStatus.CANCELLED:
                charge.status = SubscriptionChargeStatus.CANCELLED
                charge.failure_reason = "Payment cancelled"
                charge.provider_reference = provider_ref
                charge.save(
                    update_fields=["status", "failure_reason", "provider_reference"]
                )
        elif status == PaymentTransactionStatus.FAILED:
            if charge.status != SubscriptionChargeStatus.FAILED:
                charge.status = SubscriptionChargeStatus.FAILED
                charge.failure_reason = "Payment failed"
                charge.provider_reference = provider_ref
                charge.save(
                    update_fields=["status", "failure_reason", "provider_reference"]
                )
        else:
            # Non-terminal state; nothing to do yet
            return charge

    refresh_subscription_status(subscription)
    return charge


def send_due_soon_sms_reminders(
    *,
    days_before: int = 5,
    as_of: Optional[timezone.datetime] = None,
    limit: int = 200,
) -> int:
    """Send SMS reminders ahead of a subscription's next due date."""

    as_of = as_of or timezone.now()
    days_before = max(1, int(days_before or 1))

    target = as_of + timedelta(days=days_before)
    target_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    target_end = target_start + timedelta(days=1)

    qs = (
        DeviceSubscription.objects.filter(
            monthly_amount__gt=0,
            next_due_at__gte=target_start,
            next_due_at__lt=target_end,
            device__deleted_at__isnull=True,
        )
        .exclude(due_reminder_for_due_at=F("next_due_at"))
        .select_related("device__user")
        .order_by("next_due_at")
    )

    sms_client = SMSClient()
    sent_count = 0

    for subscription in qs[:limit]:
        device = subscription.device
        user = getattr(device, "user", None)
        if not user:
            continue

        phone_number = (user.phone_number or "").strip()
        if not phone_number:
            phone_number = (device.phone_number or "").strip()
        if not phone_number:
            continue

        device_name = device.device_name or device.hardware_identifier
        due_local = timezone.localtime(subscription.next_due_at)
        message = (
            f"Reminder: Your fire alarm subscription for {device_name} is due on "
            f"{due_local:%d %b %Y}. Please renew to avoid service interruption."
        )

        try:
            sms_client.send_text(
                phone_number,
                message,
                session_id=f"subscription:{subscription.pk}",
                extra_payload={"type": "due_soon"},
            )
        except Exception:
            logger.exception(
                "Failed to send due reminder SMS for subscription %s", subscription.pk
            )
            continue

        subscription.due_reminder_for_due_at = subscription.next_due_at
        subscription.due_reminder_sent_at = timezone.now()
        subscription.save(
            update_fields=["due_reminder_for_due_at", "due_reminder_sent_at"]
        )
        sent_count += 1

    return sent_count
