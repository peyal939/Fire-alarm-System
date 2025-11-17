from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class SmsGatewayConfig:
    url: str
    api_key: str
    secret_key: str
    caller_id: str
    timeout: int
    enabled: bool


class SMSClient:
    def __init__(self, config: Optional[SmsGatewayConfig] = None) -> None:
        cfg = config or SmsGatewayConfig(
            url=settings.SMS_GATEWAY["url"],
            api_key=settings.SMS_GATEWAY["api_key"],
            secret_key=settings.SMS_GATEWAY["secret_key"],
            caller_id=settings.SMS_GATEWAY["caller_id"],
            timeout=settings.SMS_GATEWAY["timeout"],
            enabled=settings.SMS_GATEWAY["enabled"],
        )
        self.config = cfg

    def send_text(
        self,
        to_number: str,
        message: str,
        *,
        session_id: str | None = None,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.config.enabled:
            logger.info("SMS gateway disabled, skipping send to %s", to_number)
            return {"status": "disabled"}

        payload = {
            "apikey": self.config.api_key,
            "secretkey": self.config.secret_key,
            "callerID": self.config.caller_id,
            "toUser": to_number,
            "messageContent": message,
        }
        if extra_payload:
            payload.update(extra_payload)

        try:
            response = requests.post(
                self.config.url,
                json=payload,
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError:
                data = {"raw": response.text}
            logger.info(
                "SMS sent to %s (session=%s)", to_number, session_id or "unknown"
            )
            return data
        except requests.RequestException as exc:  # pragma: no cover - network errors
            logger.exception(
                "Failed to send SMS to %s (session=%s)", to_number, session_id
            )
            raise exc
