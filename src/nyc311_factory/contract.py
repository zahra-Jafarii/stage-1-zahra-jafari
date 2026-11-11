"""Generic dataset contract: columns, types, allowed values, row rules.

A contract describes one dataset. The validator, the cleaner and the
duplicate tracker read it, so none of them knows a specific dataset.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from .exceptions import ConfigError
from .parsing import DTYPE_CHECKS

# reason codes that do not depend on a dataset
DUPLICATE_KEY = "DUPLICATE_KEY"
DUPLICATE_CONTENT = "DUPLICATE_CONTENT"

# a row rule gets one raw record and returns a list of reason codes
RowRule = Callable[[dict], list]


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str                          # one of parsing.DTYPE_CHECKS
    nullable: bool = True
    allowed: Optional[frozenset] = None
    case_insensitive: bool = False      # compare and store allowed values in upper case
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    fill_value: Optional[str] = None    # missing value is filled, not quarantined
    missing_code: Optional[str] = None
    invalid_code: Optional[str] = None

    @property
    def missing_reason(self) -> str:
        return self.missing_code or f"MISSING_{self.name.upper()}"

    @property
    def invalid_reason(self) -> str:
        return self.invalid_code or f"INVALID_{self.name.upper()}"


@dataclass(frozen=True)
class Contract:
    name: str
    source_columns: tuple               # columns read from the source
    derived_columns: tuple              # columns created by the factory
    key_column: str                     # makes a record unique
    content_columns: tuple              # same values here means "same call twice"
    required_columns: tuple             # absence means the source schema changed
    row_rules: tuple = ()
    text_only_source: bool = True       # source sends text only (JSON API, CSV)

    @property
    def source_names(self) -> list:
        return [column.name for column in self.source_columns]

    @property
    def output_names(self) -> list:
        return self.source_names + [column.name for column in self.derived_columns]

    @property
    def output_columns(self) -> list:
        return list(self.source_columns) + list(self.derived_columns)

    @property
    def quarantine_names(self) -> list:
        return self.source_names + ["reason_codes"]


def check_contract(contract: Contract) -> None:
    # a broken contract is a configuration mistake, not a data problem
    names = contract.source_names
    if len(set(names)) != len(names):
        raise ConfigError(f"contract {contract.name}: repeated column names")
    for column in contract.output_columns:
        if column.dtype not in DTYPE_CHECKS:
            raise ConfigError(f"contract {contract.name}: unknown dtype {column.dtype!r}")
    for group in (contract.required_columns, contract.content_columns):
        unknown = [name for name in group if name not in names]
        if unknown:
            raise ConfigError(f"contract {contract.name}: unknown columns {unknown}")
    if contract.key_column not in names:
        raise ConfigError(f"contract {contract.name}: key column is not a source column")
