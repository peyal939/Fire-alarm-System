from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications.sms import SMSClient

from .models import PhoneOTP
from .tasks import send_otp_sms_task


@dataclass
class OTPConfig:
    code_length: int
    ttl_seconds: int
    resend_cooldown_seconds: int
    max_attempts: int
    max_daily_sends: int
    test_bypass_code: str | None


class OTPSessionManager:
    def __init__(self, *, purpose: str) -> None:
        self.purpose = purpose
        self.cfg = OTPConfig(
            code_length=settings.OTP_SETTINGS["code_length"],
            ttl_seconds=settings.OTP_SETTINGS["ttl_seconds"],
            resend_cooldown_seconds=settings.OTP_SETTINGS["resend_cooldown_seconds"],
            max_attempts=settings.OTP_SETTINGS["max_attempts"],
            max_daily_sends=settings.OTP_SETTINGS["max_daily_sends"],
            test_bypass_code=settings.OTP_SETTINGS.get("test_bypass_code") or None,
        )
        self.sms_client = SMSClient()
        self.purpose_label = {
            PhoneOTP.Purpose.LOGIN: "login",
            PhoneOTP.Purpose.REGISTER: "registration",
            PhoneOTP.Purpose.PASSWORD_RESET: "password reset",
        }.get(purpose, "verification")

    # ------------------------------------------------------------------ helpers
    def _generate_code(self) -> str:
        # Use digits-only code for SMS friendliness
        return "".join(
            secrets.choice("0123456789") for _ in range(self.cfg.code_length)
        )

    def _within_daily_limit(self, phone_number: str) -> bool:
        start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        count = PhoneOTP.objects.filter(
            phone_number=phone_number,
            purpose=self.purpose,
            created_at__gte=start_of_day,
        ).count()
        return count < self.cfg.max_daily_sends

    def _render_message(self, code: str) -> str:
        template = settings.OTP_SETTINGS["sms_template"]
        minutes = max(1, round(self.cfg.ttl_seconds / 60))
        return template.format(
            code=code,
            minutes=minutes,
            purpose=self.purpose_label,
        )

    # ------------------------------------------------------------------ API
    @transaction.atomic
    def create_session(
        self,
        *,
        phone_number: str,
        user=None,
        metadata: Optional[Dict[str, Any]] = None,
        skip_rate_limits: bool = False,
    ) -> PhoneOTP:
        if not skip_rate_limits and not self._within_daily_limit(phone_number):
            raise ValueError("Daily OTP request limit exceeded for this number")

        code = self._generate_code()
        expires_at = timezone.now() + timedelta(seconds=self.cfg.ttl_seconds)

        session = PhoneOTP.objects.create(
            phone_number=phone_number,
            purpose=self.purpose,
            user=user,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        session.set_code(code)
        session.save(update_fields=["code_hash"])

        message = self._render_message(code)

        if settings.OTP_SETTINGS["send_async"]:
            session.mark_pending_send()

            def enqueue_sms():
                send_otp_sms_task.delay(str(session.session_id), message)

            transaction.on_commit(enqueue_sms)
        else:
            self.sms_client.send_text(
                phone_number,
                message,
                session_id=str(session.session_id),
            )
            session.mark_sent()
        return session

    def can_resend(self, session: PhoneOTP) -> bool:
        if session.is_verified or session.is_locked:
            return False
        if session.is_expired:
            return False
        if not session.last_sent_at:
            return True
        elapsed = timezone.now() - session.last_sent_at
        return elapsed >= timedelta(seconds=self.cfg.resend_cooldown_seconds)

    @transaction.atomic
    def resend_session(self, session: PhoneOTP) -> PhoneOTP:
        if session.purpose != self.purpose:
            raise ValueError("OTP purpose mismatch for resend")
        if not self.can_resend(session):
            raise ValueError("OTP cannot be resent yet")

        code = self._generate_code()
        expires_at = timezone.now() + timedelta(seconds=self.cfg.ttl_seconds)

        session.set_code(code)
        session.expires_at = expires_at
        session.attempts = 0
        session.locked_at = None
        session.last_error = ""
        session.save(
            update_fields=[
                "code_hash",
                "expires_at",
                "attempts",
                "locked_at",
                "last_error",
                "updated_at",
            ]
        )

        message = self._render_message(code)

        if settings.OTP_SETTINGS["send_async"]:
            session.mark_pending_send()

            def enqueue_sms():
                send_otp_sms_task.delay(str(session.session_id), message)

            transaction.on_commit(enqueue_sms)
        else:
            self.sms_client.send_text(
                session.phone_number,
                message,
                session_id=str(session.session_id),
            )
            session.mark_sent()

        return session

    def verify_code(self, session: PhoneOTP, code: str) -> bool:
        if session.is_locked or session.is_verified:
            return False
        if session.is_expired:
            session.last_error = "expired"
            session.save(update_fields=["last_error", "updated_at"])
            return False

        if self.cfg.test_bypass_code and code == self.cfg.test_bypass_code:
            session.mark_verified()
            return True

        if not session.check_code(code):
            session.increment_attempts()
            if session.attempts >= self.cfg.max_attempts:
                session.mark_locked("max_attempts")
            return False

        session.mark_verified()
        return True
