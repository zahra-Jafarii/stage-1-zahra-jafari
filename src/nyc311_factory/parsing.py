"""Small pure parsers shared by validator and transformer."""
import re
from datetime import datetime
from typing import Optional

ZIP_PATTERN = re.compile(r"\d{5}")


def is_filled(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def parse_timestamp(value) -> Optional[datetime]:
    # keeps seconds only, drops fractions
    if not is_filled(value):
        return None
    try:
        return datetime.fromisoformat(value.strip()[:19])
    except ValueError:
        return None


def clean_zip(value) -> Optional[str]:
    # returns a 5-digit zip or None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) == 10 and text[5] == "-":
        text = text[:5]
    if ZIP_PATTERN.fullmatch(text) and text != "00000":
        return text
    return None