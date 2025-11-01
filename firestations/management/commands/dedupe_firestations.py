from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from firestations.models import FireStation
from firestations.phone_utils import collect_candidate_numbers


class Command(BaseCommand):
    help = "Remove duplicate fire station entries that share contact numbers, keeping the latest record for each phone number."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Identify duplicates without deleting any records.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options.get("dry_run", False)

        stations = list(
            FireStation.objects.select_related(
                "district", "district__division"
            ).order_by("-updated_at", "-created_at", "-id")
        )

        numbers_seen: dict[str, tuple[int, str]] = {}
        duplicates: set[int] = set()
        for station in stations:
            numbers = collect_candidate_numbers(station)
            if not numbers:
                continue

            duplicate_number = None
            keeper_info = None
            for number in numbers:
                info = numbers_seen.get(number)
                if info and info[0] != station.id:
                    duplicate_number = number
                    keeper_info = info
                    break

            if duplicate_number and keeper_info:
                duplicates.add(station.id)
                kept_id, kept_name = keeper_info
                self.stdout.write(
                    self.style.WARNING(
                        f"Removing {station.name_en} (ID {station.id}) – shares {duplicate_number} with {kept_name} (ID {kept_id})."
                    )
                )
                continue

            for number in numbers:
                numbers_seen[number] = (station.id, station.name_en)

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("No duplicate phone numbers found."))
            return

        summary = ", ".join(str(pk) for pk in sorted(duplicates))
        self.stdout.write(
            self.style.NOTICE(
                f"Identified {len(duplicates)} duplicate station(s) to remove: {summary}."
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Dry run enabled – no records were deleted.")
            )
            return

        with transaction.atomic():
            deleted, _ = FireStation.objects.filter(id__in=duplicates).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} duplicate station(s). Remaining unique phone numbers: {len(numbers_seen)}"
            )
        )
