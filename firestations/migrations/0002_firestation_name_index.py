from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("firestations", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="firestation",
            index=models.Index(fields=["name_en", "name_bn"], name="fire_name_idx"),
        ),
    ]
