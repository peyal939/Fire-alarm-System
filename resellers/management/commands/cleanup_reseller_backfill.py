from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from resellers.models import Reseller, ResellerInventory, ResellerPurchaseOrder


@dataclass(frozen=True)
class CleanupResult:
    scanned: int = 0
    candidates: int = 0
    po_soft_deleted: int = 0
    inventory_soft_deleted: int = 0
    skipped_not_safe: int = 0


class Command(BaseCommand):
    help = (
        "Cleanup incorrect reseller purchase orders created by the backfill. "
        "Targets only rows whose notes include '(Backfilled from existing platform order)'. "
        "By default, removes those where order.ordered_at < reseller.activated_at (or reseller.created_at)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reseller-id",
            type=int,
            default=0,
            help="Only cleanup for a specific reseller id (0 = all).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without writing to DB.",
        )
        parser.add_argument(
            "--all-backfilled",
            action="store_true",
            help=(
                "Remove ALL backfilled reseller purchase orders (notes match), regardless of activation/created cutoff. "
                "Use with caution."
            ),
        )

    def handle(self, *args, **options):
        reseller_id = int(options.get("reseller_id") or 0)
        dry_run = bool(options.get("dry_run"))
        all_backfilled = bool(options.get("all_backfilled"))

        resellers = Reseller.objects.filter(deleted_at__isnull=True)
        if reseller_id:
            resellers = resellers.filter(id=reseller_id)

        backfill_note = "(Backfilled from existing platform order)"
        now = timezone.now()

        result = CleanupResult()

        for reseller in resellers.iterator(chunk_size=200):
            cutoff = reseller.activated_at or reseller.created_at

            qs = (
                ResellerPurchaseOrder.objects.select_related("order")
                .filter(reseller=reseller, deleted_at__isnull=True, notes__icontains=backfill_note)
                .order_by("id")
            )

            if not all_backfilled and cutoff:
                qs = qs.filter(order__ordered_at__lt=cutoff)

            for po in qs.iterator(chunk_size=200):
                result = CleanupResult(
                    scanned=result.scanned + 1,
                    candidates=result.candidates + 1,
                    po_soft_deleted=result.po_soft_deleted,
                    inventory_soft_deleted=result.inventory_soft_deleted,
                    skipped_not_safe=result.skipped_not_safe,
                )

                inv_qs = ResellerInventory.objects.filter(
                    reseller=reseller,
                    purchase_order=po.order,
                    deleted_at__isnull=True,
                )

                # Safety: if anything was already sold/reserved/returned/defective, don't touch.
                not_safe = inv_qs.exclude(status=ResellerInventory.Status.AVAILABLE).exists() or inv_qs.filter(
                    sold_to_customer__isnull=False
                ).exists()

                if not_safe:
                    if dry_run:
                        self.stdout.write(
                            f"[DRY-RUN] SKIP (not safe): PO {po.id} order {po.order_id} reseller {reseller.id} has non-available inventory"
                        )
                    result = CleanupResult(
                        scanned=result.scanned,
                        candidates=result.candidates,
                        po_soft_deleted=result.po_soft_deleted,
                        inventory_soft_deleted=result.inventory_soft_deleted,
                        skipped_not_safe=result.skipped_not_safe + 1,
                    )
                    continue

                inv_count = inv_qs.count()

                if dry_run:
                    self.stdout.write(
                        f"[DRY-RUN] DELETE: PO {po.id} order {po.order_id} reseller {reseller.id} + inventory_items={inv_count}"
                    )
                    continue

                with transaction.atomic():
                    inv_qs.update(deleted_at=now, deleted_by=None, updated_at=now)
                    po.deleted_at = now
                    po.deleted_by = None
                    po.updated_at = now
                    po.save(update_fields=["deleted_at", "deleted_by", "updated_at"])

                result = CleanupResult(
                    scanned=result.scanned,
                    candidates=result.candidates,
                    po_soft_deleted=result.po_soft_deleted + 1,
                    inventory_soft_deleted=result.inventory_soft_deleted + inv_count,
                    skipped_not_safe=result.skipped_not_safe,
                )

        self.stdout.write(self.style.SUCCESS("Cleanup complete."))
        self.stdout.write(
            "Summary: "
            f"scanned={result.scanned}, candidates={result.candidates}, "
            f"po_soft_deleted={result.po_soft_deleted}, inventory_soft_deleted={result.inventory_soft_deleted}, "
            f"skipped_not_safe={result.skipped_not_safe}"
        )
