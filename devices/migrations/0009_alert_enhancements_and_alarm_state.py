from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


def copy_triggered_to_last_triggered(apps, schema_editor):
    Alert = apps.get_model("devices", "Alert")
    Alert.objects.filter(last_triggered_at__isnull=True).update(
        last_triggered_at=models.F("triggered_at")
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0008_device_phone_number"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="alert",
            name="acknowledged_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="alert",
            name="acknowledged_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="acknowledged_alerts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="alert",
            name="last_reminder_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="alert",
            name="last_triggered_at",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="alert",
            name="reminder_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="DeviceAlarmState",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "safe_reading_streak",
                    models.PositiveSmallIntegerField(default=0),
                ),
                (
                    "next_reminder_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "active_alert",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="alarm_states",
                        to="devices.alert",
                    ),
                ),
                (
                    "device",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="alarm_state",
                        to="devices.device",
                    ),
                ),
            ],
        ),
        migrations.RunPython(copy_triggered_to_last_triggered, noop_reverse),
    ]
