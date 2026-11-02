"""Load and validate the JSON config."""
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .exceptions import ConfigError


@dataclass(frozen=True)
class Config:
    api_url: str
    start_date: str
    end_date: str
    key_suffix_digits: tuple
    http_method: str
    page_size: int
    max_retries: int
    backoff_base_seconds: float
    timeout_seconds: float
    quarantine_threshold: float
    top_complaint_types: int
    raw_dir: str
    curated_dir: str
    population_file: str
    population_zip_column: str
    population_value_column: str
    app_token_env: str
    track_memory: bool

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


def validate_config(config: Config) -> None:
    try:
        start, end = config.start, config.end
    except ValueError as error:
        raise ConfigError(f"invalid date in config: {error}") from error
    if start >= end:
        raise ConfigError("start_date must be before end_date")
    if config.http_method.upper() not in ("GET", "POST"):
        raise ConfigError("http_method must be GET or POST")
    if not 0 <= config.quarantine_threshold <= 1:
        raise ConfigError("quarantine_threshold must be in [0, 1]")
    if config.page_size <= 0 or config.max_retries < 0:
        raise ConfigError("page_size must be > 0 and max_retries >= 0")
    for digit in config.key_suffix_digits:
        if len(digit) != 1 or not digit.isdigit():
            raise ConfigError(f"bad key suffix digit: {digit!r}")


def load_config(path: str) -> Config:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"cannot read config {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")
    raw["key_suffix_digits"] = tuple(raw.get("key_suffix_digits", ()))
    try:
        config = Config(**raw)
    except TypeError as error:
        raise ConfigError(f"config keys mismatch: {error}") from error
    validate_config(config)
    return config


def with_window(config: Config, start: str, end: str) -> Config:
    new_config = replace(config, start_date=start, end_date=end)
    validate_config(new_config)
    return new_config


def ensure_dir(path: str) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory