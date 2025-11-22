from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0003_subscriptioncharge_cycles_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="devicesubscription",
            name="due_reminder_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="devicesubscription",
            name="due_reminder_for_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
