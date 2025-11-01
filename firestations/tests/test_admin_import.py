import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class FireStationAdminImportTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            email="admin@example.com",
            password="test-pass-123",
            full_name="Admin User",
        )
        self.client.force_login(self.user)

    def test_admin_trigger_invokes_import_command(self):
        def fake_call_command(*args, **kwargs):
            stdout = kwargs.get("stdout")
            if stdout:
                stdout.write(
                    "Import completed. Stations created: 1, updated: 1, total processed: 2.\n"
                )
            return None

        with patch(
            "firestations.admin.call_command", side_effect=fake_call_command
        ) as mock_command:
            response = self.client.post(
                reverse("admin:firestations_firestation_import")
            )

        self.assertRedirects(
            response, reverse("admin:firestations_firestation_changelist")
        )
        mock_command.assert_called_once()
        args, kwargs = mock_command.call_args
        self.assertEqual(args[0], "import_fire_departments")
        self.assertTrue(kwargs["no_purge"])
        self.assertIn("stdout", kwargs)
        self.assertIn("stderr", kwargs)

        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("default dataset" in str(message) for message in messages))
        self.assertTrue(any("Import completed" in str(message) for message in messages))

    def test_rejects_get_requests(self):
        response = self.client.get(reverse("admin:firestations_firestation_import"))
        self.assertEqual(response.status_code, 405)

    def test_admin_trigger_accepts_csv_upload(self):
        csv_content = (
            "division,division_en,district,district_en,serial,office_name,"
            "office_name_en,contact_text,contact_numbers,source_pdf\n"
            "ঢাকা বিভাগ,Dhaka Division,ঢাকা জেলা,Dhaka District,1,ঢাকা ফায়ার স্টেশন,"
            "Dhaka Fire Station,০১৭11-111111,01711111111|01722222222,ঢাকা.pdf\n"
        ).encode("utf-8")
        upload = SimpleUploadedFile("custom.csv", csv_content, content_type="text/csv")

        recorded_path = {}

        def fake_call_command(*args, **kwargs):
            stdout = kwargs.get("stdout")
            if stdout:
                stdout.write(
                    "Import completed. Stations created: 1, updated: 0, total processed: 1.\n"
                )
            recorded_path["path"] = kwargs.get("path")

        with patch(
            "firestations.admin.call_command", side_effect=fake_call_command
        ) as mock_command:
            response = self.client.post(
                reverse("admin:firestations_firestation_import"),
                {"csv_file": upload},
            )

        self.assertRedirects(
            response, reverse("admin:firestations_firestation_changelist")
        )
        mock_command.assert_called_once()
        path = recorded_path.get("path")
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(".csv"))
        self.assertFalse(os.path.exists(path))

        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("uploaded CSV" in str(message) for message in messages))

    def test_rejects_non_csv_uploads(self):
        upload = SimpleUploadedFile("bad.txt", b"not csv", content_type="text/plain")

        with patch("firestations.admin.call_command") as mock_command:
            response = self.client.post(
                reverse("admin:firestations_firestation_import"),
                {"csv_file": upload},
            )

        self.assertRedirects(
            response, reverse("admin:firestations_firestation_changelist")
        )
        mock_command.assert_not_called()
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any(".csv extension" in str(message) for message in messages))
