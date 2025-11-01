"""Utility to convert division-wise fire service PDF lists into a CSV dataset.

This script expects the source PDFs to live under ``fire department info/`` at the
repository root. The output CSV is written to ``data/fire_departments.csv`` with
UTF-8 encoding so Bangla labels remain intact.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

import pdfplumber
from bangla import convert_bangla_digit_to_english_digit
from bijoy2unicode import converter


LOGGER = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT_DIR / "fire department info"
OUTPUT_CSV = ROOT_DIR / "data" / "fire_departments.csv"
GEO_DATA_DIR = ROOT_DIR / "data" / "geo"
DIVISIONS_JSON = GEO_DATA_DIR / "divisions.json"
DISTRICTS_JSON = GEO_DATA_DIR / "districts.json"
UPAZILAS_JSON = GEO_DATA_DIR / "upazilas.json"

ENGLISH_NAME_OVERRIDES = {
    "Barisal": "Barishal",
    "Barisal Sadar": "Barishal Sadar",
    "Chattagram": "Chattogram",
    "Comilla": "Cumilla",
    "Comilla Sadar": "Cumilla Sadar",
    "Coxsbazar": "Cox's Bazar",
    "Coxsbazar Sadar": "Cox's Bazar Sadar",
    "Jessore": "Jashore",
    "Jessore Sadar": "Jashore Sadar",
    "Sadarsouth": "Sadar Dakshin",
}

BANGLA_PHRASE_TRANSLATIONS = {
    "ফায়ার সার্ভিস ও সিভিল ডিফেন্স স্টেশন": "Fire Service and Civil Defence Station",
    "ফায়ার সার্ভিস ও সিভিল ডিফেন্স স্টেশন": "Fire Service and Civil Defence Station",
    "ফায়ার সার্ভিস ও সিভিল ডিফেন্স": "Fire Service and Civil Defence",
    "ফায়ার সার্ভিস ও সিভিল ডিফেন্স": "Fire Service and Civil Defence",
    "ফায়ার সার্ভিস": "Fire Service",
    "ফায়ার সার্ভিস": "Fire Service",
    "ফায়ার স্টেশন": "Fire Station",
    "ফায়ার স্টেশন": "Fire Station",
    "উপপরিচালক": "Deputy Director",
    "উপপরিচালক,": "Deputy Director,",
    "সহকারী পরিচালক": "Assistant Director",
    "সহকারী পরিচালক,": "Assistant Director,",
    "উপ সহকারী পরিচালক": "Deputy Assistant Director",
    "উপ সহকারী পরিচালক,": "Deputy Assistant Director,",
    "উপসহকারী পরিচালক": "Deputy Assistant Director",
    "উপসহকারী পরিচালক,": "Deputy Assistant Director,",
    "অতিরিক্ত পরিচালক": "Additional Director",
    "অতিরিক্ত পরিচালক,": "Additional Director,",
    "বিভাগ": "Division",
    "জেলা": "District",
    "সিটি কর্পোরেশন": "City Corporation",
    "উপজেলা": "Upazila",
    "সদর": "Sadar",
    "জোন": "Zone",
    "রিজিয়ন": "Region",
    "উপকেন্দ্র": "Sub Centre",
    "বিমানবন্দর": "Airport",
    "নদী": "River",
    "স্থল-কাম": "Land-cum",
    "মিনি": "Mini",
    "বয়রা": "Boyra",
    "মংলা": "Mongla",
    "কেরানীগঞ্জ": "Keraniganj",
    "সচিবালায়": "Secretariat",
    "ডিইপিজেড": "DEPZ",
    "সিইপিজেড": "CEPZ",
}

POST_TRANSLATION_FIXES = {
    "Cepz": "CEPZ",
    "Depz": "DEPZ",
}

BIJOY_CONVERTER = converter.Unicode()
BANGLA_DIGITS = set("০১২৩৪৫৬৭৮৯")
BIJOY_TRIGGER_CHARS = set(
    "†‡•ƒ¤¢£¥§¨©ª«¬­®¯°±²³´µ¶·¸¹º»¼½¾¿"  # common Bijoy glyphs
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"  # ASCII letters
)
SERIAL_LINE_PATTERN = re.compile(r"^([০-৯0-9]+)\s*[\u09F7\u09F8\u09F9\.:\)]?\s+(.*)$")
PHONE_SPLIT_PATTERN = re.compile(r"[,;\/\u0964\u09F7\u09CE|]+")  # includes Bangla danda
TEXT_FIXES: tuple[tuple[str, str], ...] = (
    ("ফোয়োর", "ফায়ার"),
    ("যশেন", "স্টেশন"),
    ("ভশেন", "স্টেশন"),
    ("জেশফনর", "স্টেশনের"),
    ("জেশন", "স্টেশন"),
    ("জশেন", "স্টেশন"),
    ("স্টশেন", "স্টেশন"),
    ("অর্ফস", "অফিস"),
    ("অর্ফস /", "অফিস /"),
    ("জ াগাফ াগ", "যোগাযোগ"),
    ("পর্রচালক", "পরিচালক"),
    ("উপপর্রচালক", "উপপরিচালক"),
    ("সাভির্স", "সার্ভিস"),
    ("সার্ভসি", "সার্ভিস"),
    ("র্সর্ভল", "সিভিল"),
    ("র্িফফন্স", "ডিফেন্স"),
    ("ির্ভাগ", "বিভাগ"),
    ("র্িভাগ", "বিভাগ"),
    ("ািফগরহাট", "বাগেরহাট"),
    ("ফশার", "যশোর"),
    ("র্িনাই হ", "ঝিনাইদহ"),
    ("কুর্িয়া", "কুষ্টিয়া"),
    ("চুয়ািাঙ্গা", "চুয়াডাঙ্গা"),
    ("জমফহরপুর", "মেহেরপুর"),
    ("ালমিাঙ্গা", "আলমডাঙ্গা"),
    ("আড়তিমোরী", "আদিতমারী"),
    ("গজোররয়ো", "গজারিয়া"),
    ("তোলতলল", "তালতলী"),
    ("পলোশবোীি", "পলাশবাড়ী"),
    ("মোন্দো", "মান্দা"),
    ("সোঘোটো", "সাঘাটা"),
    ("সোদুল্লোপুর", "সাদুল্লাপুর"),
    ("ড়ড়িররবন্দর", "চিরিরবন্দর"),
    (" ন ী", " নদী"),
    ("ÿ", "ক্ষ"),
    ("ির্নাই হ", "ঝিনাইদহ"),
    ("জ ৌলতপুর", "দৌলতপুর"),
    ("াফকাপ", "দাকোপ"),
    ("জতরখা া", "তেরখাদা"),
    ("ির্করগাছা", "ঝিকরগাছা"),
    ("ািঘারপাড়া", "বাঘারপাড়া"),
    ("েীিননগর", "জীবননগর"),
    ("শনি া", "দর্শনা"),
    ("সারাব া", "সারাবাড়ী"),
    ("কাসসমপুর", "কাশিমপুর"),
    ("যযেরেহোে য োে টস্থ োেম নীে", "জাজিরা হাইওয়ে টোল প্লাজা"),
    ("োেরশয়োনী", "কাশিয়ানী"),
    ("ভ োলোহোট", "ভোলাহাট"),
    ("নোচ োল", "নাচোল"),
    ("দুপ োস য়ো", "দুপচাঁচিয়া"),
    ("য ৌহজং", "লৌহজং"),
    ("খুলনা ফায়ার স্টেশন, য়িরা", "খুলনা ফায়ার স্টেশন, বয়রা"),
    ("খার্লশপুর", "খালিশপুর"),
    ("খানােহান", "খানজাহান"),
    ("ডুমুর্রয়া", "ডুমুরিয়া"),
    ("টিয়িাঘাটা", "বটিয়াঘাটা"),
    ("মুর্েিনগর", "মুজিবনগর"),
    ("কুমিের্টালা", "কুমিরতলা"),
    ("পলস্নবী", "পল্লবী"),
)

DISTRICT_CORRECTIONS = {
    "ািফগরহাট জেলা": "বাগেরহাট জেলা",
    "কুর্িয়া জেলা": "কুষ্টিয়া জেলা",
    "চুয়ািাঙ্গা জেলা": "চুয়াডাঙ্গা জেলা",
    "জমফহরপুর জেলা": "মেহেরপুর জেলা",
    "ির্নাই হ জেলা": "ঝিনাইদহ জেলা",
    "ফশার জেলা": "যশোর জেলা",
    "কুমিলস্না জেলা": "কুমিল্লা জেলা",
    "লÿীপুর জেলা": "লক্ষ্মীপুর জেলা",
}

BENGALI_BASE_LATIN = {
    "অ": "o",
    "আ": "a",
    "ই": "i",
    "ঈ": "i",
    "উ": "u",
    "ঊ": "u",
    "ঋ": "ri",
    "ঌ": "li",
    "এ": "e",
    "ঐ": "oi",
    "ও": "o",
    "ঔ": "ou",
    "ক": "k",
    "খ": "kh",
    "গ": "g",
    "ঘ": "gh",
    "ঙ": "ng",
    "চ": "ch",
    "ছ": "chh",
    "জ": "j",
    "ঝ": "jh",
    "ঞ": "ny",
    "ট": "t",
    "ঠ": "th",
    "ড": "d",
    "ঢ": "dh",
    "ণ": "n",
    "ত": "t",
    "থ": "th",
    "দ": "d",
    "ধ": "dh",
    "ন": "n",
    "প": "p",
    "ফ": "f",
    "ব": "b",
    "ভ": "bh",
    "ম": "m",
    "য": "y",
    "র": "r",
    "ল": "l",
    "শ": "sh",
    "ষ": "sh",
    "স": "s",
    "হ": "h",
    "ড়": "r",
    "ঢ়": "rh",
    "য়": "y",
    "ৎ": "t",
    "ং": "ng",
    "ঃ": "h",
    "ঁ": "n",
    "ৠ": "rri",
    "ৡ": "lli",
    "০": "0",
    "১": "1",
    "২": "2",
    "৩": "3",
    "৪": "4",
    "৫": "5",
    "৬": "6",
    "৭": "7",
    "৮": "8",
    "৯": "9",
}

BENGALI_VOWEL_SIGNS = {
    "া": "a",
    "ি": "i",
    "ী": "i",
    "ু": "u",
    "ূ": "u",
    "ৃ": "ri",
    "ৄ": "ri",
    "ৢ": "li",
    "ৣ": "li",
    "ে": "e",
    "ৈ": "oi",
    "ো": "o",
    "ৌ": "ou",
    "ৗ": "ou",
    "ঁ": "n",
    "ঃ": "h",
}


def transliterate_bn_to_en(value: str) -> str:
    """Return a simple ASCII transliteration for search-friendly English labels."""

    if not value:
        return ""

    tokens: List[str] = []
    index = 0
    while index < len(value):
        char = value[index]

        if char.isascii():
            tokens.append(char)
            index += 1
            continue

        if char == "্":
            next_char = value[index + 1] if index + 1 < len(value) else ""
            if next_char == "য":
                tokens.append("y")
                index += 2
                continue
            index += 1
            continue

        mapped = BENGALI_VOWEL_SIGNS.get(char)
        if mapped is not None:
            tokens.append(mapped)
            index += 1
            continue

        base = BENGALI_BASE_LATIN.get(char)
        if base is not None:
            tokens.append(base)
        else:
            tokens.append(" ")
        index += 1

    transliterated = "".join(tokens)
    transliterated = re.sub(r"[^0-9A-Za-z]+", " ", transliterated).strip()
    if not transliterated:
        return ""

    return " ".join(part.capitalize() for part in transliterated.split())


def replace_many(value: str, replacements: dict[str, str]) -> str:
    if not value or not replacements:
        return value

    updated = value
    for source in sorted(replacements, key=len, reverse=True):
        updated = updated.replace(source, replacements[source])
    return updated


def _load_admin_table(path: Path, table_name: str) -> List[dict[str, str]]:
    if not path.exists():
        LOGGER.warning("Geo dataset missing: %s", path)
        return []

    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError:
        LOGGER.exception("Failed to parse geo dataset %s", path)
        return []

    for block in payload:
        if (
            isinstance(block, dict)
            and block.get("type") == "table"
            and block.get("name") == table_name
        ):
            data = block.get("data", [])
            return [row for row in data if isinstance(row, dict)]

    LOGGER.warning("Table '%s' not found in %s", table_name, path)
    return []


@lru_cache()
def get_geo_replacements() -> List[tuple[str, str]]:
    pairs: List[tuple[str, str]] = []
    for path, table_name in (
        (DIVISIONS_JSON, "divisions"),
        (DISTRICTS_JSON, "districts"),
        (UPAZILAS_JSON, "upazilas"),
    ):
        for row in _load_admin_table(path, table_name):
            bn_name = (row.get("bn_name") or "").strip()
            en_name = (row.get("name") or "").strip()
            if not bn_name or not en_name:
                continue
            en_name = ENGLISH_NAME_OVERRIDES.get(en_name, en_name)
            variants = {bn_name}
            if "য়" in bn_name:
                variants.add(bn_name.replace("য়", "য়"))
            if "য়" in bn_name:
                variants.add(bn_name.replace("য়", "য়"))
            for variant in variants:
                pairs.append((variant, en_name))

    return sorted(pairs, key=lambda item: len(item[0]), reverse=True)


def replace_geo_terms(value: str) -> str:
    updated = value
    for bn_name, en_name in get_geo_replacements():
        updated = updated.replace(bn_name, en_name)
    return updated


def convert_label_to_english(value: str) -> str:
    if not value:
        return ""

    replaced = replace_geo_terms(value)
    replaced = replace_many(replaced, BANGLA_PHRASE_TRANSLATIONS)
    replaced = convert_bangla_digit_to_english_digit(replaced)
    transliterated = transliterate_bn_to_en(replaced)
    transliterated = re.sub(r"\s+", " ", transliterated).strip()
    transliterated = replace_many(transliterated, POST_TRANSLATION_FIXES)
    return transliterated


@dataclass
class FireDepartmentEntry:
    division: str
    division_en: str
    district: str
    district_en: str
    serial: Optional[int]
    office_name: str
    office_name_en: str
    contact_text: str
    contact_numbers: List[str]
    source_pdf: Path

    def as_csv_row(self) -> List[str]:
        serial_text = str(self.serial) if self.serial is not None else ""
        normalised_contacts = "|".join(self.contact_numbers)
        return [
            self.division,
            self.division_en,
            self.district,
            self.district_en,
            serial_text,
            self.office_name,
            self.office_name_en,
            self.contact_text,
            normalised_contacts,
            self.source_pdf.name,
        ]


def apply_text_fixes(value: str) -> str:
    fixed = value
    for old, new in TEXT_FIXES:
        fixed = fixed.replace(old, new)
    return fixed


def bijoy_to_unicode(text: Optional[str]) -> str:
    if not text:
        return ""

    if any(char in BIJOY_TRIGGER_CHARS for char in text):
        return BIJOY_CONVERTER.convertBijoyToUnicode(text)

    return text


def is_probable_district_line(line: str) -> bool:
    if not line:
        return False

    starts_with_digit = line[0].isdigit() or line[0] in BANGLA_DIGITS
    if starts_with_digit:
        return False

    candidates = (
        "জেলা",
        "জলো",  # some PDFs contain a malformed 'জেলা'
        "সিটি কর্পোরেশন",
        "সিটি করপোরেশন",
        "মহানগর",
        "মেট্রোপলিটন",
        "উপাঞ্চল",
        "রেঞ্জ",
    )
    if any(keyword in line for keyword in candidates):
        # Filter obvious table headers that include these keywords
        if "অফিস" in line or "স্টেশন" in line or "নতুন" in line:
            return False
        return True

    return False


def clean_district_label(label: str) -> str:
    label = re.sub(r"\s+", " ", label.replace("(", " ("))
    label = label.replace("জলো", "জেলা")
    label = apply_text_fixes(label)
    label = DISTRICT_CORRECTIONS.get(label, label)
    return label.strip()


def extract_division_name(line: str) -> str:
    cleaned = apply_text_fixes(line)
    cleaned = cleaned.replace("ফায়ার সার্ভিস ও সিভিল ডিফেন্স", "")
    cleaned = cleaned.replace(",", " ").strip()

    if "বিভাগ" in cleaned:
        head, _, _ = cleaned.rpartition("বিভাগ")
        tokens = [token for token in head.split() if token]
        if tokens:
            return f"{tokens[-1]} বিভাগ"
    return cleaned or line.strip()


def extract_serial_and_remainder(line: str) -> Optional[tuple[Optional[int], str]]:
    match = SERIAL_LINE_PATTERN.match(line)
    if not match:
        return None

    serial_token, remainder = match.groups()
    try:
        serial = int(convert_bangla_digit_to_english_digit(serial_token))
    except ValueError:
        serial = None
    return serial, remainder.strip()


def sanitize_contact_numbers(raw_contact: str) -> List[str]:
    if not raw_contact:
        return []

    cleaned = convert_bangla_digit_to_english_digit(raw_contact)
    cleaned = cleaned.replace("–", "-").replace("—", "-")

    # Preserve leading plus signs before stripping non-digit separators.
    tokens: List[str] = []
    for chunk in PHONE_SPLIT_PATTERN.split(cleaned):
        chunk = chunk.strip()
        if not chunk:
            continue

        # Allow inline parentheses or hyphen separators by stripping them.
        sign = "+" if chunk.startswith("+") else ""
        chunk = chunk[1:] if sign else chunk
        digits_only = re.sub(r"[^0-9]", "", chunk)
        if len(digits_only) >= 5:
            tokens.append(sign + digits_only)

    return tokens


def split_name_and_contact(remainder: str) -> tuple[str, str]:
    if not remainder:
        return "", ""

    # Locate the first long digit run (>= 5 chars) to split name vs contacts.
    match = re.search(r"[০-৯0-9][০-৯0-9\-\+]{4,}", remainder)
    if not match:
        return remainder.strip(), ""

    name_part = remainder[: match.start()].strip(" \u09e4\u09f7,;:-")
    contact_part = remainder[match.start() :].strip()
    return name_part or remainder.strip(), contact_part


def iter_pdf_lines(path: Path) -> Iterator[str]:
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            raw_text = page.extract_text() or ""
            unicode_text = bijoy_to_unicode(raw_text)
            for line in unicode_text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                yield stripped


def collect_entries_for_pdf(path: Path) -> List[FireDepartmentEntry]:
    division: Optional[str] = None
    district: Optional[str] = None
    entries: List[FireDepartmentEntry] = []

    for raw_line in iter_pdf_lines(path):
        line = apply_text_fixes(raw_line)

        if not division and "বিভাগ" in line and "ফায়ার" in line:
            division = extract_division_name(line)
            LOGGER.debug("Detected division '%s' from %s", division, path.name)
            continue

        if is_probable_district_line(line):
            district = clean_district_label(line)
            LOGGER.debug("Switching to district '%s' (%s)", district, path.name)
            continue

        if "ক্র" in line and "নং" in line:
            # Table header, skip.
            continue

        parsed = extract_serial_and_remainder(line)
        if not parsed:
            continue

        if not district:
            LOGGER.warning(
                "Skipping row with no district context: %s (%s)", line, path.name
            )
            continue

        serial, remainder = parsed
        office_name, contact_text = split_name_and_contact(remainder)
        office_name = apply_text_fixes(office_name)
        contact_text = apply_text_fixes(contact_text)
        contacts = sanitize_contact_numbers(contact_text)

        division_label = division or path.stem
        entries.append(
            FireDepartmentEntry(
                division=division_label,
                division_en=convert_label_to_english(division_label),
                district=district,
                district_en=convert_label_to_english(district),
                serial=serial,
                office_name=office_name,
                office_name_en=convert_label_to_english(office_name),
                contact_text=contact_text,
                contact_numbers=contacts,
                source_pdf=path,
            )
        )

    return entries


def write_csv(entries: Iterable[FireDepartmentEntry], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "division",
        "division_en",
        "district",
        "district_en",
        "serial",
        "office_name",
        "office_name_en",
        "contact_text",
        "contact_numbers",
        "source_pdf",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for entry in entries:
            writer.writerow(entry.as_csv_row())


def main(paths: Optional[List[Path]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    pdf_paths = paths or sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_paths:
        LOGGER.error("No PDF files found under %s", PDF_DIR)
        return 1

    all_entries: List[FireDepartmentEntry] = []
    for pdf_path in pdf_paths:
        LOGGER.info("Processing %s", pdf_path.name)
        entries = collect_entries_for_pdf(pdf_path)
        LOGGER.info("  -> extracted %s rows", len(entries))
        all_entries.extend(entries)

    write_csv(all_entries, OUTPUT_CSV)
    LOGGER.info(
        "Wrote %s rows to %s", len(all_entries), OUTPUT_CSV.relative_to(ROOT_DIR)
    )
    return 0


if __name__ == "__main__":
    selected_files = [Path(arg) for arg in sys.argv[1:]] if len(sys.argv) > 1 else None
    sys.exit(main(selected_files))
