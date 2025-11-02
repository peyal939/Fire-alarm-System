from __future__ import annotations

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from firestations.models import Division, District, FireStation
from firestations.phone_utils import collect_candidate_numbers


class Command(BaseCommand):
    help = "Import fire department offices from the generated CSV dataset."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--path",
            type=str,
            help="Optional absolute/relative path to the CSV file. Defaults to data/fire_departments.csv.",
        )
        parser.add_argument(
            "--no-purge",
            action="store_true",
            help="Do not delete existing data before importing. By default the command clears the tables first.",
        )

    def handle(self, *args, **options) -> None:
        csv_path = self._resolve_path(options.get("path"))

        if not csv_path.exists():
            raise CommandError(f"CSV file not found: {csv_path}")

        self.stdout.write(
            self.style.NOTICE(f"Loading fire departments from {csv_path}")
        )

        with csv_path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        if not rows:
            self.stdout.write(
                self.style.WARNING("No data rows found in CSV - nothing to import.")
            )
            return

        with transaction.atomic():
            if not options.get("no_purge"):
                FireStation.objects.all().delete()
                District.objects.all().delete()
                Division.objects.all().delete()
                self.stdout.write(
                    self.style.SUCCESS("Cleared existing fire station data.")
                )

            numbers_seen: dict[str, int] = {}
            duplicates_removed = 0

            if options.get("no_purge"):
                for existing in FireStation.objects.select_related(
                    "district", "district__division"
                ):
                    for number in collect_candidate_numbers(existing):
                        numbers_seen[number] = existing.id

            created, updated = 0, 0
            for row in rows:
                division = self._get_or_update_division(
                    row.get("division", ""), row.get("division_en", "")
                )
                district = self._get_or_update_district(
                    division, row.get("district", ""), row.get("district_en", "")
                )
                station, was_created = self._create_or_update_station(district, row)
                duplicates_removed += self._deduplicate_by_phone(numbers_seen, station)

                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Import completed. Stations created: {created}, updated: {updated}, "
                    "total processed: {total}. Duplicate contacts removed: {dedup}."
                ).format(
                    created=created,
                    updated=updated,
                    total=len(rows),
                    dedup=duplicates_removed,
                )
            )
        )

    def _resolve_path(self, supplied_path: str | None) -> Path:
        if supplied_path:
            return Path(supplied_path).expanduser().resolve()
        return settings.BASE_DIR / "data" / "fire_departments.csv"

    def _normalise(self, value: str | None) -> str:
        return (value or "").strip()

    def _get_or_update_division(self, name_bn: str, name_en: str) -> Division:
        name_bn = self._normalise(name_bn)
        name_en = self._normalise(name_en)
        division, _ = Division.objects.update_or_create(
            name_bn=name_bn,
            defaults={"name_en": name_en or name_bn},
        )
        return division

    def _get_or_update_district(
        self, division: Division, name_bn: str, name_en: str
    ) -> District:
        name_bn = self._normalise(name_bn)
        name_en = self._normalise(name_en)
        district, _ = District.objects.update_or_create(
            division=division,
            name_bn=name_bn,
            defaults={"name_en": name_en or name_bn},
        )
        if name_en and district.name_en != name_en:
            district.name_en = name_en
            district.save(update_fields=("name_en", "updated_at"))
        return district

    def _create_or_update_station(
        self, district: District, row: dict[str, str]
    ) -> tuple[FireStation, bool]:
        name_bn = self._normalise(row.get("office_name"))
        name_en = self._normalise(row.get("office_name_en")) or name_bn
        serial = self._parse_int(row.get("serial"))
        contact_text = self._normalise(row.get("contact_text"))
        contact_numbers_raw = self._normalise(row.get("contact_numbers"))
        source_pdf = self._normalise(row.get("source_pdf"))

        lookup = {"district": district, "name_bn": name_bn}
        if serial is not None:
            lookup["serial"] = serial

        station, created = FireStation.objects.get_or_create(
            defaults={
                "name_en": name_en,
                "serial": serial,
                "contact_text": contact_text,
                "contact_numbers": contact_numbers_raw,
                "source_pdf": source_pdf,
            },
            **lookup,
        )

        fields_to_update: list[str] = []
        if station.name_en != name_en:
            station.name_en = name_en
            fields_to_update.append("name_en")
        if station.serial != serial:
            station.serial = serial
            fields_to_update.append("serial")
        if station.contact_text != contact_text:
            station.contact_text = contact_text
            fields_to_update.append("contact_text")
        if station.contact_numbers != contact_numbers_raw:
            station.contact_numbers = contact_numbers_raw
            fields_to_update.append("contact_numbers")
        if station.source_pdf != source_pdf:
            station.source_pdf = source_pdf
            fields_to_update.append("source_pdf")

        if fields_to_update:
            fields_to_update.append("updated_at")
            station.save(update_fields=tuple(fields_to_update))
        return station, created

    def _parse_int(self, value: str | None) -> int | None:
        value = self._normalise(value)
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _deduplicate_by_phone(
        self, numbers_seen: dict[str, int], station: FireStation
    ) -> int:
        numbers = collect_candidate_numbers(station)
        if not numbers:
            return 0

        # Remove stale mappings for this station first
        stale_keys = [key for key, val in numbers_seen.items() if val == station.id]
        for key in stale_keys:
            if key not in numbers:
                numbers_seen.pop(key, None)

        removed_ids: set[int] = set()
        for number in numbers:
            existing_id = numbers_seen.get(number)
            if existing_id and existing_id != station.id:
                removed_ids.add(existing_id)

        if removed_ids:
            FireStation.objects.filter(id__in=removed_ids).delete()
            keys_to_drop = [
                key for key, val in numbers_seen.items() if val in removed_ids
            ]
            for key in keys_to_drop:
                numbers_seen.pop(key, None)

        for number in numbers:
            numbers_seen[number] = station.id

        return len(removed_ids)
