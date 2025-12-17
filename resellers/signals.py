"""resellers.signals

Reseller Signals

- Auto-create a `ResellerPurchaseOrder` whenever a reseller-admin user places a
    platform `Order` through existing checkout flows.
- Auto-populate `ResellerInventory` when `OrderFulfillment` rows are created.
- Backfill `ResellerInventory` for already-fulfilled orders when the
    `ResellerPurchaseOrder` link is created later.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from products.models import Order, OrderFulfillment

from .models import ResellerInventory, ResellerPurchaseOrder

logger = logging.getLogger(__name__)


def _calc_original_amount(order: Order) -> Decimal:
    """Best-effort original amount from package pricing."""
    try:
        qty = int(order.quantity or 0)
        masters = int(order.number_of_master_devices or 0)
        price_per_device = Decimal(getattr(order.package, "price_per_device", 0) or 0)
        mrf = Decimal(getattr(order.package, "mrf", 0) or 0)
        return (price_per_device * qty) + (mrf * masters)
    except Exception:
        return Decimal(order.amount or 0)


def _ensure_inventory_for_order(*, reseller, order: Order) -> None:
    """Create missing inventory items for existing fulfillments of an order."""
    fulfillments = order.fulfillments.filter(deleted_at__isnull=True)
    if not fulfillments.exists():
        return

    # Compute per-device purchase price from reseller purchase final amount.
    try:
        po = ResellerPurchaseOrder.objects.get(order=order, deleted_at__isnull=True)
        per_device = (po.final_amount / Decimal(order.quantity or 1)).quantize(Decimal("0.01"))
    except Exception:
        per_device = Decimal("0.00")

    for f in fulfillments:
        ResellerInventory.objects.get_or_create(
            reseller=reseller,
            hardware_identifier=f.hardware_identifier,
            defaults={
                "device_role": f.device_role,
                "master_hardware_identifier": f.master_hardware_identifier,
                "purchase_order": order,
                "purchase_price": per_device,
                "status": ResellerInventory.Status.AVAILABLE,
                "created_by": order.updated_by or order.created_by,
            },
        )


@receiver(post_save, sender=OrderFulfillment)
def populate_reseller_inventory(sender, instance, created, **kwargs):
    """
    When an OrderFulfillment is created, check if the order belongs to a reseller.
    If so, automatically create a ResellerInventory item.
    """
    if not created:
        return
    
    fulfillment = instance
    order = fulfillment.order
    
    if not order:
        return
    
    # Check if this order has a reseller purchase order linked
    try:
        reseller_purchase = ResellerPurchaseOrder.objects.select_related(
            'reseller'
        ).get(order=order, deleted_at__isnull=True)
    except ResellerPurchaseOrder.DoesNotExist:
        # Not a reseller order, skip
        return
    
    reseller = reseller_purchase.reseller
    
    # Calculate purchase price per device
    # final_amount / order.quantity
    if order.quantity and order.quantity > 0:
        purchase_price = reseller_purchase.final_amount / Decimal(order.quantity)
    else:
        purchase_price = Decimal("0.00")
    
    # Create inventory item
    try:
        with transaction.atomic():
            ResellerInventory.objects.get_or_create(
                reseller=reseller,
                hardware_identifier=fulfillment.hardware_identifier,
                defaults={
                    "device_role": fulfillment.device_role,
                    "master_hardware_identifier": fulfillment.master_hardware_identifier,
                    "purchase_order": order,
                    "purchase_price": purchase_price.quantize(Decimal("0.01")),
                    "status": ResellerInventory.Status.AVAILABLE,
                    "created_by": order.updated_by or order.created_by,
                },
            )
            logger.info(
                "Created reseller inventory item for %s (reseller: %s, order: %s)",
                fulfillment.hardware_identifier,
                reseller.company_name,
                order.id
            )
    except Exception as e:
        logger.error(
            "Failed to create reseller inventory for fulfillment %s: %s",
            fulfillment.hardware_identifier, str(e)
        )


@receiver(post_save, sender=Order)
def auto_link_reseller_purchase_order(sender, instance, created, **kwargs):
    """If a reseller-admin user creates an Order via existing flows, link it."""
    if not created:
        return

    order = instance
    if getattr(order, "deleted_at", None) is not None:
        return

    user = getattr(order, "user", None)
    reseller = getattr(user, "reseller_account", None)
    if not reseller:
        return

    # Only active resellers should have reseller purchase flow tracked.
    # (Pending resellers can still create orders, but we don't want to treat
    # those as reseller inventory-bearing purchases.)
    if not getattr(reseller, "is_active", False):
        return

    # Avoid duplicates.
    if hasattr(order, "reseller_purchase"):
        return

    original_amount = _calc_original_amount(order)
    final_amount = Decimal(order.amount or 0)
    discount_applied = (original_amount - final_amount)
    if discount_applied < Decimal("0.00"):
        discount_applied = Decimal("0.00")

    try:
        with transaction.atomic():
            po = ResellerPurchaseOrder.objects.create(
                reseller=reseller,
                order=order,
                original_amount=original_amount.quantize(Decimal("0.01")),
                discount_applied=discount_applied.quantize(Decimal("0.01")),
                final_amount=final_amount.quantize(Decimal("0.01")),
                is_credit_purchase=False,
                notes="(Auto-linked from platform order)",
                created_by=order.created_by,
            )
            # If fulfillments already exist (admin fulfilled quickly), backfill.
            _ensure_inventory_for_order(reseller=reseller, order=order)
            logger.info(
                "Auto-linked Order %s to ResellerPurchaseOrder %s for reseller %s",
                order.id,
                po.id,
                reseller.company_name,
            )
    except Exception as e:
        logger.error("Failed to auto-link reseller purchase order for Order %s: %s", order.id, str(e))
