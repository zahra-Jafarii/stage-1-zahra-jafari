"""Small pure parsers shared by validator and transformer."""
import re
from datetime import datetime
from typing import Optional

ZIP_PATTERN = re.compile(r"\d{5}")
BOOL_TEXT = {"true", "false", "0", "1"}


def is_missing(value) -> bool:
    # None, NaN and blank text all count as "no value"
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    return isinstance(value, str) and value.strip() == ""


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


def to_number(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_integer_text(value) -> bool:
    number = to_number(value)
    return number is not None and number == int(number)


def is_bool_value(value) -> bool:
    return isinstance(value, bool) or str(value).strip().lower() in BOOL_TEXT


# dtype name -> check that tells whether a non-missing raw value is usable
DTYPE_CHECKS = {
    "str": lambda value: isinstance(value, str),
    "int": is_integer_text,
    "float": lambda value: to_number(value) is not None,
    "datetime": lambda value: parse_timestamp(value) is not None,
    "zip5": lambda value: clean_zip(value) is not None,
    "bool": is_bool_value,
}
