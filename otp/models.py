from __future__ import annotations

import uuid
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


class PhoneOTP(models.Model):
    class Purpose(models.TextChoices):
        REGISTER = "register", "Register"
        LOGIN = "login", "Login"
        PASSWORD_RESET = "password_reset", "Password reset"

    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    phone_number = models.CharField(max_length=32, db_index=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="otp_sessions",
    )
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    resend_count = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["phone_number", "purpose"]),
            models.Index(fields=["session_id"]),
            models.Index(fields=["expires_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"OTP {self.purpose} for {self.phone_number}"

    # Helpers -----------------------------------------------------------------
    def set_code(self, code: str) -> None:
        self.code_hash = make_password(code)

    def check_code(self, code: str) -> bool:
        return check_password(code, self.code_hash)

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    def mark_verified(self) -> None:
        self.verified_at = timezone.now()
        self.locked_at = None
        self.save(update_fields=["verified_at", "locked_at", "updated_at"])

    def mark_locked(self, reason: str | None = None) -> None:
        self.locked_at = timezone.now()
        if reason:
            self.last_error = reason
        self.save(update_fields=["locked_at", "last_error", "updated_at"])

    def increment_attempts(self) -> None:
        self.attempts += 1
        self.save(update_fields=["attempts", "updated_at"])

    def mark_sent(self) -> None:
        self.resend_count += 1
        self.last_sent_at = timezone.now()
        self.save(update_fields=["resend_count", "last_sent_at", "updated_at"])

    def mark_pending_send(self) -> None:
        self.last_sent_at = timezone.now()
        self.save(update_fields=["last_sent_at", "updated_at"])
