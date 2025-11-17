from __future__ import annotations

import logging

from celery import shared_task

from notifications.sms import SMSClient
from .models import PhoneOTP

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_otp_sms_task(self, session_uuid: str, message: str) -> None:
    try:
        session = PhoneOTP.objects.get(session_id=session_uuid)
    except PhoneOTP.DoesNotExist:  # pragma: no cover - race condition
        logger.warning("OTP session %s missing before resend", session_uuid)
        return

    if session.is_expired or session.is_verified or session.is_locked:
        logger.info(
            "Skipping resend for session %s (expired=%s, verified=%s, locked=%s)",
            session_uuid,
            session.is_expired,
            session.is_verified,
            session.is_locked,
        )
        return

    sms_client = SMSClient()
    sms_client.send_text(session.phone_number, message, session_id=session_uuid)
    session.mark_sent()
