from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PhoneOTP",
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
                    "session_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("phone_number", models.CharField(db_index=True, max_length=32)),
                (
                    "purpose",
                    models.CharField(
                        choices=[
                            ("register", "Register"),
                            ("login", "Login"),
                            ("password_reset", "Password reset"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("code_hash", models.CharField(max_length=128)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("resend_count", models.PositiveSmallIntegerField(default=0)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField()),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="otp_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="phoneotp",
            index=models.Index(
                fields=["phone_number", "purpose"], name="otp_phone_purpose_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="phoneotp",
            index=models.Index(fields=["session_id"], name="otp_session_idx"),
        ),
        migrations.AddIndex(
            model_name="phoneotp",
            index=models.Index(fields=["expires_at"], name="otp_expires_idx"),
        ),
    ]
