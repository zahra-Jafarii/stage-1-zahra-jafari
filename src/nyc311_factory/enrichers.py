"""Reference-table joins that can also compare a column with the reference."""
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from .exceptions import ConfigError, DataValidationError

TOP_LIMIT = 10


def load_reference_table(path: str, key_column: str, columns: dict,
                         key_cleaner: Callable, numeric: tuple = ()) -> pd.DataFrame:
    """Read a clean reference csv. `columns` maps file column -> output column."""
    try:
        table = pd.read_csv(path, dtype=str)
    except OSError as error:
        raise ConfigError(f"cannot read reference file {path}: {error}") from error
    needed = [key_column, *columns]
    if any(name not in table.columns for name in needed):
        raise ConfigError(f"reference file {path} must have columns {needed}")
    table = table[needed].rename(columns={key_column: "join_key", **columns})
    table["join_key"] = table["join_key"].map(key_cleaner)
    for name in numeric:
        table[name] = pd.to_numeric(table[name], errors="coerce")
    table = table.dropna(subset=["join_key", *numeric])
    if table["join_key"].duplicated().any():
        raise DataValidationError(f"reference file {path} has repeated keys")
    return table.reset_index(drop=True)


@dataclass
class ConsistencyTally:
    """Counts how often a column disagrees with the reference."""
    rows_total: int = 0
    rows_comparable: int = 0
    rows_key_unmatched: int = 0
    mismatch_rows: int = 0
    pairs: Counter = field(default_factory=Counter)
    keys: Counter = field(default_factory=Counter)

    def update(self, keys: pd.Series, case_values: pd.Series, reference_values: pd.Series) -> None:
        has_reference = reference_values.notna()
        differs = (has_reference & (case_values != reference_values)).fillna(False).astype(bool)
        self.rows_total += len(keys)
        self.rows_comparable += int(has_reference.sum())
        self.rows_key_unmatched += int((~has_reference).sum())
        self.mismatch_rows += int(differs.sum())
        pairs = zip(case_values[differs], reference_values[differs])
        self.pairs.update(pairs)
        self.keys.update(keys[differs])

    def report(self) -> dict:
        percent = self.mismatch_rows / self.rows_comparable * 100 if self.rows_comparable else 0.0
        return {
            "rows_total": self.rows_total,
            "rows_comparable": self.rows_comparable,
            "rows_key_unmatched": self.rows_key_unmatched,
            "mismatch_rows": self.mismatch_rows,
            "mismatch_pct": round(percent, 4),
            "top_mismatch_pairs": top_pairs(self.pairs),
            "top_mismatch_keys": top_keys(self.keys),
        }


def top_pairs(pairs: Counter) -> list:
    ranked = sorted(pairs.items(), key=lambda item: (-item[1], item[0]))[:TOP_LIMIT // 2]
    return [{"case_value": case, "reference_value": reference, "rows": rows}
            for (case, reference), rows in ranked]


def top_keys(keys: Counter) -> dict:
    ranked = sorted(keys.items(), key=lambda item: (-item[1], item[0]))[:TOP_LIMIT]
    return {key: rows for key, rows in ranked}


class ReferenceJoin:
    """Adds reference columns to every batch (many rows to one reference row)."""

    def __init__(self, name: str, table: pd.DataFrame, join_column: str,
                 compare: Optional[tuple] = None):
        # compare = (column in the data, column brought in from the reference)
        self.name = name
        self.table = table
        self.join_column = join_column
        self.compare = compare
        self.rows_before = 0
        self.rows_after = 0
        self.tally = ConsistencyTally()

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        joined = frame.merge(self.table, left_on=self.join_column, right_on="join_key",
                             how="left", validate="many_to_one")
        joined = joined.drop(columns="join_key")
        if len(joined) != len(frame):
            raise DataValidationError(f"{self.name}: join changed the row count")
        self.rows_before += len(frame)
        self.rows_after += len(joined)
        if self.compare:
            case_column, reference_column = self.compare
            self.tally.update(joined[self.join_column], joined[case_column],
                              joined[reference_column])
        return joined

    def join_report(self) -> dict:
        return {"rows_before": self.rows_before, "rows_after": self.rows_after}

    def consistency_report(self) -> Optional[dict]:
        return self.tally.report() if self.compare else None
