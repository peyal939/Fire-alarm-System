from django.db import migrations, models, connection
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0003_alter_alert_options"),
    ]

    def add_columns_if_missing(apps, schema_editor):
        Device = apps.get_model("devices", "Device")
        table = Device._meta.db_table

        # Helper to check column existence using Django introspection (portable)
        def column_exists(col: str) -> bool:
            introspection = schema_editor.connection.introspection
            with connection.cursor() as cursor:
                try:
                    description = introspection.get_table_description(cursor, table)
                    cols = [getattr(c, "name", None) or c[0] for c in description]
                    return col in cols
                except Exception:
                    return False

        # Add device_role if missing
        if not column_exists("device_role"):
            field = models.CharField(
                max_length=10,
                choices=[("master", "Master"), ("slave", "Slave")],
                default="master",
                db_index=True,
            )
            field.set_attributes_from_name("device_role")
            schema_editor.add_field(Device, field)

        # Add master_id if missing
        if not column_exists("master_id"):
            field = models.ForeignKey(
                to="devices.Device",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="slaves",
                null=True,
                blank=True,
            )
            field.set_attributes_from_name("master")
            schema_editor.add_field(Device, field)

    operations = [
        migrations.RunPython(add_columns_if_missing, migrations.RunPython.noop),
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
