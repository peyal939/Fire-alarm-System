from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0003_alter_alert_options"),
    ]

    operations = [
        # The columns already exist in DB (added manually or via prior edits),
        # so we add them to the migration STATE only to let constraints reference them.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="device",
                    name="device_role",
                    field=models.CharField(
                        choices=[("master", "Master"), ("slave", "Slave")],
                        db_index=True,
                        default="master",
                        max_length=10,
                    ),
                ),
                migrations.AddField(
                    model_name="device",
                    name="master",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="slaves",
                        to="devices.device",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="device",
            constraint=models.CheckConstraint(
                name="device_master_null_if_role_master",
                check=(
                    models.Q(("device_role", "master"), ("master__isnull", True))
                    | ~models.Q(("device_role", "master"))
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="device",
            constraint=models.CheckConstraint(
                name="device_master_not_null_if_role_slave",
                check=(
                    models.Q(("device_role", "slave"), ("master__isnull", False))
                    | ~models.Q(("device_role", "slave"))
                ),
            ),
        ),
    ]
