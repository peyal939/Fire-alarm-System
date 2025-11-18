from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def backfill_subscriptions(apps, schema_editor):
    Device = apps.get_model("devices", "Device")
    DeviceSubscription = apps.get_model("subscriptions", "DeviceSubscription")

    existing_sub_ids = set(
        DeviceSubscription.objects.values_list("device_id", flat=True)
    )
    devices = (
        Device.objects.filter(deleted_at__isnull=True, originating_order__isnull=False)
        .select_related("originating_order__package")
        .iterator(chunk_size=500)
    )
    now = timezone.now()
    for device in devices:
        if device.id in existing_sub_ids:
            continue
        activation_time = device.registered_at or now
        first_cycle_end = activation_time + timedelta(days=30)
        order = getattr(device, "originating_order", None)
        package = getattr(order, "package", None)
        monthly_amount = getattr(package, "mrf", 0) or 0
        DeviceSubscription.objects.create(
            device_id=device.id,
            originating_order_id=getattr(order, "id", None),
            monthly_amount=monthly_amount,
            status="active",
            billing_anchor=activation_time,
            last_paid_through=first_cycle_end,
            next_due_at=first_cycle_end,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_subscriptions, noop_reverse),
    ]
