"""Load and validate the JSON config."""
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .exceptions import ConfigError

SOURCE_TYPES = ("api", "csv", "jsonl")
DESTINATIONS = ("csv", "database")


@dataclass(frozen=True)
class Config:
    # quality gate and output settings (generic)
    quarantine_threshold: float
    curated_dir: str
    # which dataset contract to use, where data comes from and where it goes
    dataset: str = ""
    source_type: str = "csv"
    input_path: str = ""
    destinations: tuple = ("csv",)
    page_size: int = 50_000
    track_memory: bool = False
    # database destination
    database_url_env: str = "DATABASE_URL"
    database_schema: str = ""
    database_cases_table: str = ""       # empty: the contract name
    database_quarantine_table: str = ""  # empty: the contract name + _quarantine
    database_load_mode: str = "replace"  # replace: swap the table; existing: reload a table you created
    # run window; used by the api source and the manifest
    start_date: str = ""
    end_date: str = ""
    # api source settings (only the nyc311 dataset uses them)
    api_url: str = ""
    key_suffix_digits: tuple = ()
    http_method: str = "GET"
    max_retries: int = 5
    backoff_base_seconds: float = 1.0
    timeout_seconds: float = 60.0
    app_token_env: str = "SOCRATA_APP_TOKEN"
    raw_dir: str = "data/raw"
    top_complaint_types: int = 10
    # population reference (only the nyc311 dataset uses it)
    population_file: str = "data/reference/population.csv"
    population_zip_column: str = "zip_code"
    population_value_column: str = "population"
    population_raw_file: str = "data/reference/population_raw.csv"
    population_report_file: str = "data/reference/population_report.json"
    population_raw_zip_column: str = "label"
    population_raw_borough_column: str = "BOROUGH_GROUP"
    population_raw_value_column: str = "POP_DENOMINATOR"
    population_borough_column: str = "borough"
    population_source_url: str = ""
    population_source_retrieved: str = ""

    @property
    def start(self) -> date:
        return date.fromisoformat(self.start_date)

    @property
    def end(self) -> date:
        return date.fromisoformat(self.end_date)

    @property
    def sample_fraction(self) -> float:
        # share of keys kept by the last-digit filter
        if not self.key_suffix_digits:
            return 1.0
        return len(self.key_suffix_digits) / 10


def validate_window(config: Config) -> None:
    if not config.start_date and not config.end_date:
        return  # window is optional for file sources
    try:
        start, end = config.start, config.end
    except ValueError as error:
        raise ConfigError(f"invalid date in config: {error}") from error
    if start >= end:
        raise ConfigError("start_date must be before end_date")


def validate_http(config: Config) -> None:
    if config.http_method.upper() not in ("GET", "POST"):
        raise ConfigError("http_method must be GET or POST")
    if config.page_size <= 0 or config.max_retries < 0:
        raise ConfigError("page_size must be > 0 and max_retries >= 0")
    for digit in config.key_suffix_digits:
        if len(digit) != 1 or not digit.isdigit():
            raise ConfigError(f"bad key suffix digit: {digit!r}")


def validate_io(config: Config) -> None:
    if config.source_type not in SOURCE_TYPES:
        raise ConfigError(f"source_type must be one of {SOURCE_TYPES}")
    if config.database_load_mode not in ("replace", "existing"):
        raise ConfigError("database_load_mode must be replace or existing")
    if config.source_type == "api" and not config.api_url:
        raise ConfigError("source_type api needs api_url")
    if config.source_type != "api" and not config.input_path:
        raise ConfigError(f"source_type {config.source_type} needs input_path")
    if not config.destinations or any(name not in DESTINATIONS for name in config.destinations):
        raise ConfigError(f"destinations must be a non-empty list of {DESTINATIONS}")


def validate_config(config: Config) -> None:
    validate_window(config)
    validate_http(config)
    validate_io(config)
    if not 0 <= config.quarantine_threshold <= 1:
        raise ConfigError("quarantine_threshold must be in [0, 1]")


def load_config(path: str) -> Config:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"cannot read config {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")
    for name in ("key_suffix_digits", "destinations"):
        if name in raw:
            raw[name] = tuple(raw[name])
    try:
        config = Config(**raw)
    except TypeError as error:
        raise ConfigError(f"config keys mismatch: {error}") from error
    validate_config(config)
    return config


def with_overrides(config: Config, **changes) -> Config:
    # command line values replace config values; None means "not given"
    given = {name: value for name, value in changes.items() if value is not None}
    new_config = replace(config, **given)
    validate_config(new_config)
    return new_config


def with_window(config: Config, start: str, end: str) -> Config:
    return with_overrides(config, start_date=start, end_date=end)


def ensure_dir(path: str) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
