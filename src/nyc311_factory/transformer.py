"""Cleaning, duplicates, derived columns, population join."""
import hashlib

import pandas as pd

from .config import Config
from .exceptions import ConfigError, DataValidationError
from .parsing import clean_zip
from .schema import (
    CONTENT_COLUMNS, DUPLICATE_CONTENT, DUPLICATE_KEY, SOURCE_COLUMNS,
)


def to_frame(records: list) -> pd.DataFrame:
    return pd.DataFrame(records, columns=SOURCE_COLUMNS)


def quarantine_frame(rejected: list) -> pd.DataFrame:
    frame = to_frame([record for record, _ in rejected])
    frame["reason_codes"] = ["|".join(codes) for _, codes in rejected]
    return frame


def content_fingerprints(frame: pd.DataFrame) -> list:
    parts = frame[CONTENT_COLUMNS].fillna("").astype(str)
    rows = ("|".join(row) for row in parts.itertuples(index=False))
    return [hashlib.md5(text.encode("utf-8")).hexdigest() for text in rows]


class DuplicateTracker:
    """Keeps seen keys and content hashes across batches (small memory)."""

    def __init__(self):
        self.seen_keys = set()
        self.seen_content = set()

    def split(self, frame: pd.DataFrame) -> tuple:
        reasons = []
        for key, fingerprint in zip(frame["unique_key"], content_fingerprints(frame)):
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


def clean_batch(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["created_date"] = parse_datetime_column(out["created_date"])
    out["closed_date"] = parse_datetime_column(out["closed_date"])
    out["incident_zip"] = out["incident_zip"].map(clean_zip)
    out["borough"] = out["borough"].astype("string").str.strip().str.upper()
    for column in ("agency", "complaint_type", "descriptor", "status"):
        out[column] = out[column].astype("string").str.strip()
    out["descriptor"] = out["descriptor"].fillna("Unknown")  # policy: unknown label
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    return add_derived_columns(out)


def add_derived_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame["closing_hours"] = (
        (frame["closed_date"] - frame["created_date"]).dt.total_seconds() / 3600
    ).round(4)
    frame["is_closed"] = frame["closed_date"].notna()  # open case: closed_date stays empty
    frame["year_month"] = frame["created_date"].dt.strftime("%Y-%m")
    return frame


def load_population(config: Config) -> pd.DataFrame:
    try:
        table = pd.read_csv(config.population_file, dtype=str)
    except OSError as error:
        raise ConfigError(f"cannot read population file: {error}") from error
    needed = [config.population_zip_column, config.population_value_column]
    if any(column not in table.columns for column in needed):
        raise ConfigError(f"population file must have columns {needed}")
    table = table[needed].rename(columns={
        config.population_zip_column: "incident_zip",
        config.population_value_column: "population",
    })
    table["incident_zip"] = table["incident_zip"].map(clean_zip)
    table["population"] = pd.to_numeric(table["population"], errors="coerce")
    table = table.dropna(subset=["incident_zip", "population"])
    if table["incident_zip"].duplicated().any():
        raise DataValidationError("population table has repeated zip codes")
    return table.reset_index(drop=True)


def attach_population(frame: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    joined = frame.merge(population, on="incident_zip", how="left", validate="many_to_one")
    if len(joined) != len(frame):
        raise DataValidationError("population join changed the row count")
    return joined