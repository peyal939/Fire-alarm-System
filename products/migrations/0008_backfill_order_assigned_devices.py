from django.db import migrations, models


def backfill_assigned_devices(apps, schema_editor):
    Order = apps.get_model("products", "Order")
    Device = apps.get_model("devices", "Device")

    counts = (
        Device.objects.exclude(originating_order__isnull=True)
        .values("originating_order")
        .annotate(total=models.Count("id"))
    )
    if not counts:
        return

    for row in counts:
        order_id = row.get("originating_order")
        total = row.get("total", 0) or 0
        if order_id:
            Order.objects.filter(pk=order_id).update(assigned_devices=total)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0007_order_assigned_devices_and_more"),
        ("devices", "0011_device_originating_order_and_more"),  # Need devices app with originating_order field
    ]

    operations = [
        migrations.RunPython(backfill_assigned_devices, noop_reverse),
    ]
