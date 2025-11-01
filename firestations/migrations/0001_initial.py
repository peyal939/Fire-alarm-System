from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Division",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name_bn",
                    models.CharField(
                        max_length=128, unique=True, verbose_name="Name (Bangla)"
                    ),
                ),
                (
                    "name_en",
                    models.CharField(
                        max_length=128, unique=True, verbose_name="Name (English)"
                    ),
                ),
                ("slug", models.SlugField(editable=False, max_length=160, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("name_en",),
                "verbose_name": "Division",
                "verbose_name_plural": "Divisions",
            },
        ),
        migrations.CreateModel(
            name="District",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name_bn",
                    models.CharField(max_length=128, verbose_name="Name (Bangla)"),
                ),
                (
                    "name_en",
                    models.CharField(max_length=128, verbose_name="Name (English)"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="districts",
                        to="firestations.division",
                    ),
                ),
            ],
            options={
                "ordering": ("division__name_en", "name_en"),
                "verbose_name": "District",
                "verbose_name_plural": "Districts",
                "unique_together": {
                    (
                        "division",
                        "name_bn",
                    ),
                    (
                        "division",
                        "name_en",
                    ),
                },
            },
        ),
        migrations.CreateModel(
            name="FireStation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name_bn",
                    models.CharField(max_length=256, verbose_name="Name (Bangla)"),
                ),
                (
                    "name_en",
                    models.CharField(max_length=256, verbose_name="Name (English)"),
                ),
                ("serial", models.IntegerField(blank=True, null=True)),
                ("contact_text", models.TextField(blank=True, default="")),
                ("contact_numbers", models.TextField(blank=True, default="")),
                (
                    "source_pdf",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "district",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stations",
                        to="firestations.district",
                    ),
                ),
            ],
            options={
                "ordering": (
                    "district__division__name_en",
                    "district__name_en",
                    "serial",
                ),
                "verbose_name": "Fire Station",
                "verbose_name_plural": "Fire Stations",
            },
        ),
        migrations.AddIndex(
            model_name="firestation",
            index=models.Index(
                fields=("district", "serial"), name="firestatio_distric_05a695_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="firestation",
            index=models.Index(
                fields=("district", "name_en"), name="firestatio_distric_099364_idx"
            ),
        ),
    ]
