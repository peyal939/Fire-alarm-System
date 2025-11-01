from __future__ import annotations

import re
from typing import Iterable, Set

BANGLA_DIGIT_TRANS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def split_possible_numbers(value: str | None) -> list[str]:
    if not value:
        return []
    cleaned = value.replace("|", " ")
    parts = re.split(r"[^0-9০-৯+]+", cleaned)
    return [part for part in parts if part.strip()]


def normalise_phone(value: str | None) -> str:
    if not value:
        return ""
    normalised = value.translate(BANGLA_DIGIT_TRANS)
    digits = "".join(ch for ch in normalised if ch.isdigit())
    if digits.startswith("880") and len(digits) >= 13:
        digits = "0" + digits[3:]
    if len(digits) < 5:
        return ""
    return digits


def collect_numbers_from_sources(
    numbers: Iterable[str] | None = None,
    raw_values: Iterable[str | None] | None = None,
) -> Set[str]:
    collected: Set[str] = set()
    if numbers:
        for number in numbers:
            normalised = normalise_phone(number)
            if normalised:
                collected.add(normalised)
    if raw_values:
        for raw in raw_values:
            for chunk in split_possible_numbers(raw):
                normalised = normalise_phone(chunk)
                if normalised:
                    collected.add(normalised)
    return collected


def collect_candidate_numbers(station) -> Set[str]:
    numbers = getattr(station, "contact_number_list", [])
    raw_values = [
        getattr(station, "contact_numbers", ""),
        getattr(station, "contact_text", ""),
    ]
    return collect_numbers_from_sources(numbers, raw_values)
