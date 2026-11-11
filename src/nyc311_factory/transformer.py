"""Contract-driven cleaning and duplicate handling for batches of records."""
import hashlib

import pandas as pd

from .contract import DUPLICATE_CONTENT, DUPLICATE_KEY, Column, Contract
from .parsing import clean_zip


def to_frame(records: list, columns: list) -> pd.DataFrame:
    return pd.DataFrame(records, columns=list(columns))


def quarantine_frame(rejected: list, contract: Contract) -> pd.DataFrame:
    frame = to_frame([record for record, _ in rejected], contract.source_names)
    frame["reason_codes"] = ["|".join(codes) for _, codes in rejected]
    return frame


def content_fingerprints(frame: pd.DataFrame, content_columns: tuple) -> list:
    parts = frame[list(content_columns)].fillna("").astype(str)
    rows = ("|".join(row) for row in parts.itertuples(index=False))
    return [hashlib.md5(text.encode("utf-8")).hexdigest() for text in rows]


class DuplicateTracker:
    """Keeps seen keys and content hashes across batches (small memory)."""

    def __init__(self, contract: Contract):
        self.key_column = contract.key_column
        self.content_columns = contract.content_columns
        self.seen_keys = set()
        self.seen_content = set()

    def split(self, frame: pd.DataFrame) -> tuple:
        reasons = []
        fingerprints = content_fingerprints(frame, self.content_columns)
        for key, fingerprint in zip(frame[self.key_column], fingerprints):
            if key in self.seen_keys:
                reasons.append(DUPLICATE_KEY)
            elif fingerprint in self.seen_content:
                reasons.append(DUPLICATE_CONTENT)
            else:
                self.seen_keys.add(key)
                self.seen_content.add(fingerprint)
                reasons.append("")
        flags = pd.Series(reasons, index=frame.index, dtype="object")
        is_duplicate = flags != ""
        duplicates = frame[is_duplicate].assign(reason_codes=flags[is_duplicate])
        return frame[~is_duplicate], duplicates


def parse_datetime_column(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype("string").str[:19], errors="coerce")


def clean_text_column(series: pd.Series, column: Column) -> pd.Series:
    text = series.astype("string").str.strip()
    text = text.mask(text == "", pd.NA)  # blank text is a missing value
    if column.allowed is not None and column.case_insensitive:
        text = text.str.upper()
    if column.fill_value is not None:
        text = text.fillna(column.fill_value)
    return text


def clean_column(series: pd.Series, column: Column) -> pd.Series:
    if column.dtype == "datetime":
        return parse_datetime_column(series)
    if column.dtype == "zip5":
        return series.map(clean_zip)
    if column.dtype in ("float", "int"):
        return pd.to_numeric(series, errors="coerce")
    return clean_text_column(series, column)


def clean_batch(frame: pd.DataFrame, contract: Contract) -> pd.DataFrame:
    out = frame.copy()
    for column in contract.source_columns:
        out[column.name] = clean_column(out[column.name], column)
    return out
