"""Record validation: returns reason codes, never drops silently."""
from datetime import datetime

from .exceptions import SchemaDriftError
from .parsing import clean_zip, is_filled, parse_timestamp
from .schema import (
    BAD_CLOSED_DATE, BAD_COORDINATES, BAD_CREATED_DATE, CLOSED_BEFORE_CREATED,
    CREATED_OUT_OF_WINDOW, INVALID_ZIP, MISSING_AGENCY, MISSING_COMPLAINT_TYPE,
    MISSING_KEY, REQUIRED_COLUMNS, UNKNOWN_BOROUGH, VALID_BOROUGHS,
)


def _is_float(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_record(record: dict, window_start: datetime, window_end: datetime) -> list:
    reasons = []
    if not is_filled(record.get("unique_key")):
        reasons.append(MISSING_KEY)

    created = parse_timestamp(record.get("created_date"))
    if created is None:
        reasons.append(BAD_CREATED_DATE)
    elif not window_start <= created < window_end:
        reasons.append(CREATED_OUT_OF_WINDOW)

    closed_raw = record.get("closed_date")
    closed = parse_timestamp(closed_raw)
    if is_filled(closed_raw) and closed is None:
        reasons.append(BAD_CLOSED_DATE)
    elif closed and created and closed < created:
        reasons.append(CLOSED_BEFORE_CREATED)

    if clean_zip(record.get("incident_zip")) is None:
        reasons.append(INVALID_ZIP)
    if not is_filled(record.get("agency")):
        reasons.append(MISSING_AGENCY)
    if not is_filled(record.get("complaint_type")):
        reasons.append(MISSING_COMPLAINT_TYPE)

    borough = record.get("borough")
    if not is_filled(borough) or borough.strip().upper() not in VALID_BOROUGHS:
        reasons.append(UNKNOWN_BOROUGH)

    for column in ("latitude", "longitude"):
        value = record.get(column)
        if is_filled(value) and not _is_float(value):
            reasons.append(BAD_COORDINATES)
            break
    return reasons


def split_valid(batch: list, window_start: datetime, window_end: datetime) -> tuple:
    valid, rejected = [], []
    for record in batch:
        reasons = validate_record(record, window_start, window_end)
        if reasons:
            rejected.append((record, reasons))
        else:
            valid.append(record)
    return valid, rejected


def check_batch_types(batch: list) -> None:
    # source sends text; any other type means the schema changed
    for record in batch:
        for column in REQUIRED_COLUMNS:
            value = record.get(column)
            if value is not None and not isinstance(value, str):
                raise SchemaDriftError(f"column {column} changed type: {type(value).__name__}")


def check_required_columns(columns_seen: set) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in columns_seen]
    if missing:
        raise SchemaDriftError(f"required columns missing from source: {missing}")