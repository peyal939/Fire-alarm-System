import csv
import os
from tempfile import NamedTemporaryFile

from django.core.management import call_command
from django.test import TestCase

from firestations.models import Division, District, FireStation


class ImportFireDepartmentsCommandTests(TestCase):
    def _write_csv(self, rows):
        fieldnames = [
            "division",
            "division_en",
            "district",
            "district_en",
            "serial",
            "office_name",
            "office_name_en",
            "contact_text",
            "contact_numbers",
            "source_pdf",
        ]
        temp_file = NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False)
        writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temp_file.flush()
        temp_file.close()
        return temp_file.name

    def test_import_creates_and_updates_records(self):
        rows = [
            {
                "division": "ঢাকা বিভাগ",
                "division_en": "Dhaka Division",
                "district": "ঢাকা জেলা",
                "district_en": "Dhaka District",
                "serial": "1",
                "office_name": "ঢাকা ফায়ার স্টেশন",
                "office_name_en": "Dhaka Fire Station",
                "contact_text": "০১৭11-111111",
                "contact_numbers": "01711111111|01722222222",
                "source_pdf": "ঢাকা.pdf",
            },
            {
                "division": "ঢাকা বিভাগ",
                "division_en": "Dhaka Division",
                "district": "ঢাকা জেলা",
                "district_en": "Dhaka District",
                "serial": "",
                "office_name": "সহকারী পরিচালক, ঢাকা",
                "office_name_en": "Assistant Director Dhaka",
                "contact_text": "০১৯00-000000",
                "contact_numbers": "01900000000",
                "source_pdf": "ঢাকা.pdf",
            },
        ]
        first_csv = self._write_csv(rows)
        self.addCleanup(lambda: os.path.exists(first_csv) and os.unlink(first_csv))

        call_command("import_fire_departments", path=first_csv)

        division = Division.objects.get()
        self.assertEqual(division.name_en, "Dhaka Division")
        self.assertEqual(division.slug, "dhaka-division")
        self.assertEqual(Division.objects.count(), 1)
        self.assertEqual(District.objects.count(), 1)
        self.assertEqual(FireStation.objects.count(), 2)

        station = FireStation.objects.get(serial=1)
        self.assertEqual(station.name_en, "Dhaka Fire Station")
        self.assertEqual(
            station.contact_number_list,
            ["01711111111", "01722222222"],
        )

        assistant_director = FireStation.objects.get(name_en="Assistant Director Dhaka")
        self.assertIsNone(assistant_director.serial)

        # Update contact text and ensure --no-purge performs an update
        rows[0]["contact_text"] = "০১৭11-333333"
        second_csv = self._write_csv(rows)
        self.addCleanup(lambda: os.path.exists(second_csv) and os.unlink(second_csv))

        call_command("import_fire_departments", path=second_csv, no_purge=True)

        station.refresh_from_db()
        self.assertEqual(station.contact_text, "০১৭11-333333")

    def test_duplicates_by_contact_number_remove_older_station(self):
        base_rows = [
            {
                "division": "ঢাকা বিভাগ",
                "division_en": "Dhaka Division",
                "district": "ঢাকা জেলা",
                "district_en": "Dhaka District",
                "serial": "1",
                "office_name": "ঢাকা ফায়ার স্টেশন",
                "office_name_en": "Dhaka Fire Station",
                "contact_text": "০১৭11-111111",
                "contact_numbers": "01711111111|01722222222",
                "source_pdf": "ঢাকা.pdf",
            },
            {
                "division": "ঢাকা বিভাগ",
                "division_en": "Dhaka Division",
                "district": "ঢাকা জেলা",
                "district_en": "Dhaka District",
                "serial": "2",
                "office_name": "গুলশান ফায়ার স্টেশন",
                "office_name_en": "Gulshan Fire Station",
                "contact_text": "০১৭55-555555",
                "contact_numbers": "01755555555",
                "source_pdf": "ঢাকা.pdf",
            },
        ]

        csv_one = self._write_csv(base_rows)
        self.addCleanup(lambda: os.path.exists(csv_one) and os.unlink(csv_one))
        call_command("import_fire_departments", path=csv_one)

        self.assertEqual(FireStation.objects.count(), 2)

        duplicate_rows = base_rows + [
            {
                "division": "ঢাকা বিভাগ",
                "division_en": "Dhaka Division",
                "district": "ঢাকা জেলা",
                "district_en": "Dhaka District",
                "serial": "3",
                "office_name": "ধনমন্ডি ফায়ার স্টেশন",
                "office_name_en": "Dhanmondi Fire Station",
                "contact_text": "Emergency line",
                "contact_numbers": "01722222222",
                "source_pdf": "ঢাকা.pdf",
            }
        ]

        csv_two = self._write_csv(duplicate_rows)
        self.addCleanup(lambda: os.path.exists(csv_two) and os.unlink(csv_two))

        call_command("import_fire_departments", path=csv_two, no_purge=True)

        stations = FireStation.objects.values_list("name_en", flat=True)
        self.assertEqual(FireStation.objects.count(), 2)
        self.assertIn("Dhanmondi Fire Station", stations)
        self.assertIn("Gulshan Fire Station", stations)
        self.assertNotIn("Dhaka Fire Station", stations)
