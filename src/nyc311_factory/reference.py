"""Build the clean population reference (zip_code, borough, population)."""
from pathlib import Path

import pandas as pd

from .config import Config
from .exceptions import ConfigError, DataValidationError
from .files import write_json_atomic
from .parsing import clean_zip
from .sinks import CsvSink

REFERENCE_COLUMNS = ["zip_code", "borough", "population"]
BOROUGHS = {"MANHATTAN", "BROOKLYN", "QUEENS", "BRONX", "STATEN ISLAND"}


def read_raw_population(config: Config) -> pd.DataFrame:
    try:
        return pd.read_csv(config.population_raw_file, dtype=str)
    except OSError as error:
        raise ConfigError(f"cannot read raw population file: {error}") from error


def select_reference_columns(table: pd.DataFrame, config: Config) -> pd.DataFrame:
    needed = [
        config.population_raw_zip_column,
        config.population_raw_borough_column,
        config.population_raw_value_column,
    ]
    missing = [column for column in needed if column not in table.columns]
    if missing:
        raise ConfigError(f"raw population file is missing columns {missing}")
    selected = table[needed].copy()
    selected.columns = REFERENCE_COLUMNS
    return selected


def split_merged_zips(table: pd.DataFrame) -> pd.DataFrame:
    # One row per zip code for merged areas such as "10001, 10118"
    out = table.copy()
    out["zip_code"] = out["zip_code"].str.split(",")
    out = out.explode("zip_code")
    out["zip_code"] = out["zip_code"].str.strip().map(clean_zip)
    return out


def clean_reference_values(table: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    out["borough"] = out["borough"].str.strip().str.upper()
    out["population"] = pd.to_numeric(out["population"], errors="coerce").round()
    return out


def keep_valid_rows(table: pd.DataFrame) -> pd.DataFrame:
    valid = table.dropna(subset=["zip_code", "population"])
    valid = valid[valid["borough"].isin(BOROUGHS)].copy()
    valid["population"] = valid["population"].astype("int64")
    return valid


def check_reference_table(table: pd.DataFrame) -> None:
    if table.empty:
        raise DataValidationError("reference table is empty after cleaning")
    if table["zip_code"].duplicated().any():
        raise DataValidationError("reference table has repeated zip codes")


def describe_reference(selected, split, final, config: Config) -> dict:
    merged = selected["zip_code"].str.contains(",", na=False)
    return {
        "source_url": config.population_source_url,
        "source_retrieved": config.population_source_retrieved,
        "raw_rows": len(selected),
        "merged_areas": int(merged.sum()),
        "rows_after_split": len(split),
        "dropped_rows": len(split) - len(final),
        "final_rows": len(final),
        "rows_per_borough": {
            name: int(count) for name, count in final["borough"].value_counts().items()
        },
        "population_range": [int(final["population"].min()), int(final["population"].max())],
    }


def build_reference(config: Config) -> tuple:
    selected = select_reference_columns(read_raw_population(config), config)
    split = split_merged_zips(selected)
    final = keep_valid_rows(clean_reference_values(split))
    check_reference_table(final)
    final = final.sort_values("zip_code").reset_index(drop=True)
    return final, describe_reference(selected, split, final, config)


def write_reference(reference: pd.DataFrame, report: dict, config: Config) -> None:
    sink = CsvSink(Path(config.population_file), REFERENCE_COLUMNS)
    sink.write(reference)
    sink.close()
    write_json_atomic(Path(config.population_report_file), report)


def is_reference_fresh(config: Config) -> bool:
    clean, raw = Path(config.population_file), Path(config.population_raw_file)
    if not clean.exists():
        return False
    return not raw.exists() or clean.stat().st_mtime >= raw.stat().st_mtime


def ensure_population_reference(config: Config) -> bool:
    # Build only when the clean file is missing or older than the raw file
    if is_reference_fresh(config):
        return False
    reference, report = build_reference(config)
    write_reference(reference, report, config)
    return True