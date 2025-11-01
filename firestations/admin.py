import os
from io import StringIO
from tempfile import NamedTemporaryFile

from django.contrib import admin, messages
from django.core.management import call_command
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.urls import path, reverse

from .models import Division, District, FireStation


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_bn", "slug")
    search_fields = ("name_en", "name_bn")


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name_en", "name_bn", "division")
    list_filter = ("division",)
    search_fields = ("name_en", "name_bn")


@admin.register(FireStation)
class FireStationAdmin(admin.ModelAdmin):
    change_list_template = "admin/firestations/firestation/change_list.html"
    list_display = (
        "name_en",
        "name_bn",
        "district",
        "serial",
        "source_pdf",
    )
    list_filter = ("district__division", "district")
    search_fields = ("name_en", "name_bn", "contact_text")
    autocomplete_fields = ("district",)
    ordering = ("district__division__name_en", "district__name_en", "serial")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-data/",
                self.admin_site.admin_view(self.import_from_csv),
                name="firestations_firestation_import",
            )
        ]
        return custom_urls + urls

    def import_from_csv(self, request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        changelist_url = reverse("admin:firestations_firestation_changelist")

        if not request.user.has_perm("firestations.add_firestation"):
            self.message_user(
                request,
                "You do not have permission to import fire station data.",
                level=messages.ERROR,
            )
            return redirect(changelist_url)

        output = StringIO()
        uploaded_file = request.FILES.get("csv_file")
        temp_path = None
        try:
            call_command_kwargs = {
                "no_purge": True,
                "stdout": output,
                "stderr": output,
            }

            if uploaded_file:
                if not uploaded_file.name.lower().endswith(".csv"):
                    self.message_user(
                        request,
                        "Please upload a file with a .csv extension.",
                        level=messages.ERROR,
                    )
                    return redirect(changelist_url)

                temp_file = NamedTemporaryFile("wb", suffix=".csv", delete=False)
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file.flush()
                temp_file.close()
                temp_path = temp_file.name
                call_command_kwargs["path"] = temp_path

            call_command(
                "import_fire_departments",
                **call_command_kwargs,
            )
        except Exception as exc:  # pragma: no cover - unexpected failure path
            self.message_user(
                request,
                f"Import failed: {exc}",
                level=messages.ERROR,
            )
            return redirect(changelist_url)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

        log_lines = [
            line.strip() for line in output.getvalue().splitlines() if line.strip()
        ]
        source_label = "uploaded CSV" if uploaded_file else "default dataset"
        summary = log_lines[-1] if log_lines else "Import completed."
        self.message_user(
            request,
            f"Fire station data import from {source_label} completed. {summary}",
            level=messages.SUCCESS,
        )
        return redirect(changelist_url)
