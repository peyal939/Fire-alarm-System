from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from products.models import Order
from resellers.models import ResellerInventory, ResellerPurchaseOrder


@dataclass(frozen=True)
class BackfillResult:
    linked_purchase_orders: int = 0
    created_inventory_items: int = 0
    skipped_already_linked: int = 0
    skipped_no_reseller: int = 0
    skipped_inactive_reseller: int = 0


def _calc_original_amount(order: Order) -> Decimal:
    try:
        qty = int(order.quantity or 0)
        masters = int(order.number_of_master_devices or 0)
        price_per_device = Decimal(getattr(order.package, "price_per_device", 0) or 0)
        mrf = Decimal(getattr(order.package, "mrf", 0) or 0)
        return (price_per_device * qty) + (mrf * masters)
    except Exception:
        return Decimal(order.amount or 0)


class Command(BaseCommand):
    help = (
        "Backfill reseller purchase orders for existing platform Orders. "
        "Creates missing ResellerPurchaseOrder rows and backfills ResellerInventory "
        "from existing fulfillments."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--order-id",
            action="append",
            dest="order_ids",
            default=[],
            help="Specific Order ID to backfill (repeatable).",
        )
        parser.add_argument(
            "--since-date",
            type=lambda s: date.fromisoformat(s),
            dest="since_date",
            default=None,
            help="Only backfill orders ordered_at >= YYYY-MM-DD.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include pending/suspended/terminated resellers.",
        )
        parser.add_argument(
            "--ignore-activation-date",
            action="store_true",
            help=(
                "Ignore reseller activated_at/created_at cutoff and backfill all matching orders. "
                "By default, only orders ordered_at >= reseller.activated_at (or reseller.created_at if missing) are linked."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to DB.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit number of orders processed (0 = no limit).",
        )

    def handle(self, *args, **options):
        order_ids = [int(x) for x in (options.get("order_ids") or [])]
        since_date: date | None = options.get("since_date")
        include_inactive: bool = bool(options.get("include_inactive"))
        ignore_activation_date: bool = bool(options.get("ignore_activation_date"))
        dry_run: bool = bool(options.get("dry_run"))
        limit: int = int(options.get("limit") or 0)

        qs = Order.objects.select_related("user", "package").prefetch_related("fulfillments")
        qs = qs.filter(deleted_at__isnull=True)
        qs = qs.filter(user__reseller_account__isnull=False)

        if order_ids:
            qs = qs.filter(id__in=order_ids)

        if since_date:
            since_dt = timezone.make_aware(timezone.datetime.combine(since_date, timezone.datetime.min.time()))
            qs = qs.filter(ordered_at__gte=since_dt)

        if not include_inactive:
            qs = qs.filter(
                user__reseller_account__status="active",
                user__reseller_account__deleted_at__isnull=True,
            )

        qs = qs.order_by("ordered_at", "id")
        if limit > 0:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(self.style.NOTICE(f"Found {total} order(s) eligible for backfill."))
        if total == 0:
            return

        result = BackfillResult()

        for order in qs.iterator(chunk_size=200):
            reseller = getattr(order.user, "reseller_account", None)
            if reseller is None:
                result = BackfillResult(
                    linked_purchase_orders=result.linked_purchase_orders,
                    created_inventory_items=result.created_inventory_items,
                    skipped_already_linked=result.skipped_already_linked,
                    skipped_no_reseller=result.skipped_no_reseller + 1,
                    skipped_inactive_reseller=result.skipped_inactive_reseller,
                )
                continue

            if (not include_inactive) and (not reseller.is_active):
                result = BackfillResult(
                    linked_purchase_orders=result.linked_purchase_orders,
                    created_inventory_items=result.created_inventory_items,
                    skipped_already_linked=result.skipped_already_linked,
                    skipped_no_reseller=result.skipped_no_reseller,
                    skipped_inactive_reseller=result.skipped_inactive_reseller + 1,
                )
                continue

            # Default safety: don't convert "pre-reseller" orders into reseller purchase orders.
            if not ignore_activation_date:
                cutoff = reseller.activated_at or reseller.created_at
                if cutoff and order.ordered_at and order.ordered_at < cutoff:
                    # Skip orders placed before reseller activation/creation.
                    continue

            if hasattr(order, "reseller_purchase"):
                result = BackfillResult(
                    linked_purchase_orders=result.linked_purchase_orders,
                    created_inventory_items=result.created_inventory_items,
                    skipped_already_linked=result.skipped_already_linked + 1,
                    skipped_no_reseller=result.skipped_no_reseller,
                    skipped_inactive_reseller=result.skipped_inactive_reseller,
                )
                continue

            original_amount = _calc_original_amount(order)
            final_amount = Decimal(order.amount or 0)
            discount_applied = original_amount - final_amount
            if discount_applied < Decimal("0.00"):
                discount_applied = Decimal("0.00")

            per_device_price = Decimal("0.00")
            if (order.quantity or 0) > 0:
                per_device_price = (final_amount / Decimal(order.quantity)).quantize(Decimal("0.01"))

            fulfillments = order.fulfillments.filter(deleted_at__isnull=True)

            if dry_run:
                self.stdout.write(
                    f"[DRY-RUN] Order {order.id}: create ResellerPurchaseOrder + backfill {fulfillments.count()} fulfillment(s)"
                )
                continue

            with transaction.atomic():
                ResellerPurchaseOrder.objects.create(
                    reseller=reseller,
                    order=order,
                    original_amount=original_amount.quantize(Decimal("0.01")),
                    discount_applied=discount_applied.quantize(Decimal("0.01")),
                    final_amount=final_amount.quantize(Decimal("0.01")),
                    is_credit_purchase=False,
                    notes="(Backfilled from existing platform order)",
                    created_by=order.created_by,
                    updated_by=order.updated_by,
                )

                created_items = 0
                for f in fulfillments:
                    _, created = ResellerInventory.objects.get_or_create(
                        reseller=reseller,
                        hardware_identifier=f.hardware_identifier,
                        defaults={
                            "device_role": f.device_role,
                            "master_hardware_identifier": f.master_hardware_identifier,
                            "purchase_order": order,
                            "purchase_price": per_device_price,
                            "status": ResellerInventory.Status.AVAILABLE,
                            "created_by": order.updated_by or order.created_by,
                        },
                    )
                    if created:
                        created_items += 1

            result = BackfillResult(
                linked_purchase_orders=result.linked_purchase_orders + 1,
                created_inventory_items=result.created_inventory_items + created_items,
                skipped_already_linked=result.skipped_already_linked,
                skipped_no_reseller=result.skipped_no_reseller,
                skipped_inactive_reseller=result.skipped_inactive_reseller,
            )

        self.stdout.write(self.style.SUCCESS("Backfill complete."))
        self.stdout.write(
            "Summary: "
            f"linked_po={result.linked_purchase_orders}, "
            f"inventory_created={result.created_inventory_items}, "
            f"skipped_already_linked={result.skipped_already_linked}, "
            f"skipped_no_reseller={result.skipped_no_reseller}, "
            f"skipped_inactive={result.skipped_inactive_reseller}"
        )
