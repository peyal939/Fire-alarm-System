from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from firestations.models import Division, District, FireStation


class FireStationDedupeCommandTests(TestCase):
    def setUp(self) -> None:
        self.division = Division.objects.create(
            name_en="Dhaka Division", name_bn="ঢাকা বিভাগ"
        )
        self.district = District.objects.create(
            division=self.division,
            name_en="Dhaka District",
            name_bn="ঢাকা জেলা",
        )

    def _create_station(self, name_en: str, numbers: str, contact_text: str = ""):
        return FireStation.objects.create(
            district=self.district,
            name_en=name_en,
            name_bn=name_en,
            serial=None,
            contact_numbers=numbers,
            contact_text=contact_text,
        )

    def test_keeps_most_recent_station_with_duplicate_number(self):
        older = self._create_station("Old Station", "01711111111")
        FireStation.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=2),
            updated_at=timezone.now() - timedelta(days=2),
        )

        newer = self._create_station("New Station", "01711111111")

        call_command("dedupe_firestations")

        self.assertTrue(FireStation.objects.filter(pk=newer.pk).exists())
        self.assertFalse(FireStation.objects.filter(pk=older.pk).exists())

    def test_dry_run_does_not_delete_records(self):
        first = self._create_station("Station A", "01722222222")
        second = self._create_station("Station B", "01722222222")

        call_command("dedupe_firestations", dry_run=True)

        self.assertTrue(FireStation.objects.filter(pk=first.pk).exists())
        self.assertTrue(FireStation.objects.filter(pk=second.pk).exists())

    def test_handles_numbers_in_contact_text(self):
        # Bangla digits should be normalised and treated as duplicates
        self._create_station("Station Text", "", contact_text="ফোন: ০১৭১১১১১১১১")
        newer = self._create_station("Station Raw", "01711111111")

        call_command("dedupe_firestations")

        self.assertTrue(FireStation.objects.filter(pk=newer.pk).exists())
        self.assertEqual(FireStation.objects.count(), 1)
