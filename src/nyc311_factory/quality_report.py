"""Auto-generated data quality report, built batch by batch while the pipeline runs."""
from collections import Counter

import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

MODE_LIMIT = 1000  # stop counting values of a column once it has more distinct values


class ColumnProfile:
    """Missing share, distinct count and range of one column, without keeping the data."""

    def __init__(self):
        self.rows = 0
        self.missing = 0
        self.hashes = []
        self.low = None
        self.high = None
        self.values = Counter()
        self.counting_values = True
        self.kind = "text"

    def update(self, series: pd.Series) -> None:
        present = series.dropna()
        self.rows += len(series)
        self.missing += len(series) - len(present)
        if present.empty:
            return
        self.hashes.append(np.unique(pd.util.hash_pandas_object(present, index=False).to_numpy()))
        if is_datetime64_any_dtype(series) or (is_numeric_dtype(series) and series.dtype != bool):
            self._update_range(present)
        else:
            self._update_values(present)

    def _update_range(self, present: pd.Series) -> None:
        self.kind = "range"
        low, high = present.min(), present.max()
        self.low = low if self.low is None else min(self.low, low)
        self.high = high if self.high is None else max(self.high, high)

    def _update_values(self, present: pd.Series) -> None:
        if not self.counting_values:
            return
        self.values.update(present.tolist())
        if len(self.values) > MODE_LIMIT:
            self.counting_values, self.values = False, Counter()

    def report(self) -> dict:
        distinct = int(np.unique(np.concatenate(self.hashes)).size) if self.hashes else 0
        info = {
            "pct_missing": round(self.missing / self.rows * 100, 4) if self.rows else 0.0,
            "n_unique": distinct,
        }
        if self.kind == "range":
            info["range"] = [self._format(self.low), self._format(self.high)]
        elif self.values:
            top = sorted(self.values.items(), key=lambda item: (-item[1], str(item[0])))[0][0]
            info["top_value"] = str(top)
        return info

    @staticmethod
    def _format(value):
        return float(value) if isinstance(value, (int, float, np.number)) else str(value)


class QualityProfiler:
    def __init__(self, columns: list):
        self.profiles = {name: ColumnProfile() for name in columns}
        self.rows = 0

    def update(self, frame: pd.DataFrame) -> None:
        self.rows += len(frame)
        for name, profile in self.profiles.items():
            profile.update(frame[name])

    def report(self, reference_checks: dict) -> dict:
        report = {
            "rows": self.rows,
            "columns": {name: profile.report() for name, profile in self.profiles.items()},
        }
        if reference_checks:
            report["reference_checks"] = reference_checks
        return report
