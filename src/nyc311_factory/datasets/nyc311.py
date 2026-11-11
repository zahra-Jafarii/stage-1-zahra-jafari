"""NYC 311 service requests: contract, derived columns, population reference."""
from datetime import datetime, time
from pathlib import Path

import pandas as pd

from ..aggregate import build_wide_table
from ..config import Config
from ..contract import Column, Contract, check_contract
from ..enrichers import ReferenceJoin, load_reference_table
from ..exceptions import ConfigError
from ..files import sha256_file
from ..parsing import clean_zip
from ..reference import ensure_population_reference
from ..rules import not_before_rule, window_rule
from ..sinks import CsvSink
from ..dataset import Dataset

VALID_BOROUGHS = frozenset({"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"})

# columns that define "same call reported twice"
CONTENT_COLUMNS = (
    "created_date", "agency", "complaint_type", "descriptor",
    "incident_address", "community_board", "latitude", "longitude",
)

# columns whose absence means the source schema changed
REQUIRED_COLUMNS = (
    "unique_key", "created_date", "agency", "complaint_type", "incident_zip", "borough",
)

# quarantine reason codes
BAD_CREATED_DATE = "BAD_CREATED_DATE"
CREATED_OUT_OF_WINDOW = "CREATED_OUT_OF_WINDOW"
BAD_CLOSED_DATE = "BAD_CLOSED_DATE"
CLOSED_BEFORE_CREATED = "CLOSED_BEFORE_CREATED"
MISSING_KEY = "MISSING_KEY"
INVALID_ZIP = "INVALID_ZIP"
MISSING_AGENCY = "MISSING_AGENCY"
MISSING_COMPLAINT_TYPE = "MISSING_COMPLAINT_TYPE"
UNKNOWN_BOROUGH = "UNKNOWN_BOROUGH"
BAD_COORDINATES = "BAD_COORDINATES"

SOURCE_COLUMNS = (
    Column("unique_key", "str", nullable=False, missing_code=MISSING_KEY),
    Column("created_date", "datetime", nullable=False,
           missing_code=BAD_CREATED_DATE, invalid_code=BAD_CREATED_DATE),
    Column("closed_date", "datetime", invalid_code=BAD_CLOSED_DATE),
    Column("agency", "str", nullable=False, missing_code=MISSING_AGENCY),
    Column("complaint_type", "str", nullable=False, missing_code=MISSING_COMPLAINT_TYPE),
    Column("descriptor", "str", nullable=False, fill_value="Unknown"),  # policy: unknown label
    Column("incident_zip", "zip5", nullable=False,
           missing_code=INVALID_ZIP, invalid_code=INVALID_ZIP),
    Column("incident_address", "str"),
    Column("borough", "str", nullable=False, allowed=VALID_BOROUGHS, case_insensitive=True,
           missing_code=UNKNOWN_BOROUGH, invalid_code=UNKNOWN_BOROUGH),
    Column("community_board", "str"),
    Column("status", "str"),
    Column("resolution_description", "str"),
    Column("latitude", "float", invalid_code=BAD_COORDINATES),
    Column("longitude", "float", invalid_code=BAD_COORDINATES),
)

DERIVED_COLUMNS = (
    Column("closing_hours", "float", min_value=0),   # empty for open cases
    Column("is_closed", "bool", nullable=False),
    Column("year_month", "str", nullable=False),
    Column("population", "float"),                   # empty when the zip is not in the reference
)


def build_contract(config: Config) -> Contract:
    window_start = datetime.combine(config.start, time.min)
    window_end = datetime.combine(config.end, time.min)
    contract = Contract(
        name="nyc311",
        source_columns=SOURCE_COLUMNS,
        derived_columns=DERIVED_COLUMNS,
        key_column="unique_key",
        content_columns=CONTENT_COLUMNS,
        required_columns=REQUIRED_COLUMNS,
        row_rules=(
            window_rule("created_date", window_start, window_end, CREATED_OUT_OF_WINDOW),
            not_before_rule("created_date", "closed_date", CLOSED_BEFORE_CREATED),
        ),
    )
    check_contract(contract)
    return contract


def add_derived_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame["closing_hours"] = (
        (frame["closed_date"] - frame["created_date"]).dt.total_seconds() / 3600
    ).round(4)
    frame["is_closed"] = frame["closed_date"].notna()  # open case: closed_date stays empty
    frame["year_month"] = frame["created_date"].dt.strftime("%Y-%m")
    return frame


def load_population_reference(config: Config) -> pd.DataFrame:
    table = load_reference_table(
        config.population_file,
        key_column=config.population_zip_column,
        columns={config.population_value_column: "population",
                 config.population_borough_column: "reference_borough"},
        key_cleaner=clean_zip,
        numeric=("population",),
    )
    table["reference_borough"] = table["reference_borough"].str.strip().str.upper()
    return table


def load_population(config: Config) -> pd.DataFrame:
    # one row per zip: incident_zip, population, reference_borough
    table = load_population_reference(config).rename(columns={"join_key": "incident_zip"})
    return table[["incident_zip", "population", "reference_borough"]]


def build_enrichers(config: Config) -> list:
    # the reference borough is compared with the borough in the 311 data
    join = ReferenceJoin("population", load_population_reference(config), "incident_zip",
                         compare=("borough", "reference_borough"))
    return [join]


def check_reference_source(config: Config) -> None:
    # the challenge asks for the link and the download date of the reference
    if not config.population_source_url or not config.population_source_retrieved:
        raise ConfigError("fill population_source_url and population_source_retrieved in the config")


def prepare(config: Config) -> None:
    check_reference_source(config)
    ensure_population_reference(config)


def describe_references(config: Config) -> dict:
    return {"population": {
        "url": config.population_source_url,
        "retrieved": config.population_source_retrieved,
        "file": Path(config.population_file).name,
        "sha256": sha256_file(Path(config.population_file)),
    }}


def build_extra_outputs(config: Config, outputs: dict) -> dict:
    # the wide table is built from cases.csv, so it needs the csv destination
    if "cases.csv" not in outputs:
        return {}
    wide = build_wide_table(outputs["cases.csv"], config)
    wide_path = Path(config.curated_dir) / "aggregate_wide.csv"
    sink = CsvSink(wide_path, list(wide.columns))
    sink.write(wide)
    sink.close()
    return {"aggregate_wide.csv": wide_path}


NYC311 = Dataset(
    name="nyc311",
    build_contract=build_contract,
    prepare=prepare,
    derive=add_derived_columns,
    build_enrichers=build_enrichers,
    describe_references=describe_references,
    build_extra_outputs=build_extra_outputs,
)
