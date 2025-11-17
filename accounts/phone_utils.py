from __future__ import annotations

import re

from dataclasses import dataclass
from typing import List, Optional

__all__ = [
    "PhoneNumber",
    "normalize_phone",
    "phone_variants",
    "ensure_normalized_phone",
]

BD_COUNTRY_CODE = "880"
SUBSCRIBER_LENGTH = 10  # digits excluding the leading zero


@dataclass(frozen=True)
class PhoneNumber:
    local: str  # e.g., 017XXXXXXXX
    e164: str  # e.g., +88017XXXXXXX


def _strip_number(value: str) -> str:
    return re.sub(r"[\s\-()]+", "", value.strip())


def _extract_subscriber_digits(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    compact = _strip_number(value)
    if not compact:
        return None

    plus = compact.startswith("+")
    digits = re.sub(r"\D", "", compact)
    if not digits:
        return None

    if plus:
        if not digits.startswith(BD_COUNTRY_CODE):
            return None
        digits = digits[len(BD_COUNTRY_CODE) :]

    elif digits.startswith(BD_COUNTRY_CODE):
        digits = digits[len(BD_COUNTRY_CODE) :]

    if digits.startswith("0"):
        digits = digits[1:]

    if len(digits) == SUBSCRIBER_LENGTH:
        return digits

    if len(digits) == SUBSCRIBER_LENGTH + len(BD_COUNTRY_CODE) and digits.startswith(
        BD_COUNTRY_CODE
    ):
        digits = digits[len(BD_COUNTRY_CODE) :]
        if len(digits) == SUBSCRIBER_LENGTH:
            return digits

    return None


def normalize_phone(value: Optional[str]) -> Optional[PhoneNumber]:
    """Normalize Bangladeshi phone numbers to local (01XXXXXXXXX) and E.164 (+8801XXXXXXXX)."""

    subscriber = _extract_subscriber_digits(value)
    if not subscriber:
        return None

    local = "0" + subscriber
    e164 = "+" + BD_COUNTRY_CODE + subscriber
    return PhoneNumber(local=local, e164=e164)


def phone_variants(value: Optional[str]) -> List[str]:
    normalized = normalize_phone(value)
    if not normalized:
        return []

    return list(dict.fromkeys([normalized.local, normalized.e164]))


def ensure_normalized_phone(value: Optional[str]) -> Optional[str]:
    normalized = normalize_phone(value)
    return normalized.local if normalized else None
