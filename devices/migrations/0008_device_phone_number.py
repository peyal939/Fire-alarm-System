from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0007_alter_device_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="phone_number",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="device",
            name="phone_number_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
