"""Helpers for the notebook EDA and sample-vs-total checks."""
import tempfile
from dataclasses import replace

import numpy as np
import pandas as pd

from .aggregate import RATE_BASE, borough_wide_table, modal_borough_by_zip, top_complaint_types
from .config import Config
from .http_client import HttpClient
from .pipeline import run_pipeline
from .contract import DUPLICATE_CONTENT, DUPLICATE_KEY


# ---------------------------------------------------------------
# Loading and basic duration statistics
# ---------------------------------------------------------------
def load_cases(path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype={"unique_key": str, "incident_zip": str},
        parse_dates=["created_date", "closed_date"],
    )


def closed_cases(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["is_closed"]].copy()


def duration_summary(hours: pd.Series) -> pd.Series:
    return hours.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95, 0.99])


def duration_by_type(closed: pd.DataFrame, top_n: int) -> pd.DataFrame:
    top_types = closed["complaint_type"].value_counts().head(top_n).index
    subset = closed[closed["complaint_type"].isin(top_types)]
    table = subset.groupby("complaint_type")["closing_hours"].agg(
        cases="size", mean_hours="mean", median_hours="median",
        p90_hours=lambda values: values.quantile(0.9), max_hours="max",
    )
    safe_median = table["median_hours"].where(table["median_hours"] > 0)
    table["mean_to_median"] = table["mean_hours"] / safe_median
    return table.sort_values("cases", ascending=False).round(2)


# ---------------------------------------------------------------
# Outliers
# ---------------------------------------------------------------
def iqr_bounds(values: pd.Series, factor: float = 1.5) -> tuple:
    q1, q3 = values.quantile(0.25), values.quantile(0.75)
    spread = q3 - q1
    return q1 - factor * spread, q3 + factor * spread


def flag_outliers_log(hours: pd.Series, factor: float = 1.5) -> pd.Series:
    # IQR on log scale because durations are right-skewed
    logged = np.log1p(hours)
    lower, upper = iqr_bounds(logged, factor)
    return (logged < lower) | (logged > upper)


# ---------------------------------------------------------------
# Group comparisons and trends
# ---------------------------------------------------------------
def median_by_group(frame: pd.DataFrame, column: str, top_n: int) -> pd.Series:
    top_values = frame[column].value_counts().head(top_n).index
    subset = frame[frame[column].isin(top_values)]
    return subset.groupby(column)["closing_hours"].median().sort_values()


def monthly_median(frame: pd.DataFrame) -> pd.Series:
    return frame.groupby("year_month")["closing_hours"].median()


def median_by_borough_and_type(closed: pd.DataFrame, top_n: int) -> pd.DataFrame:
    top_types = closed["complaint_type"].value_counts().head(top_n).index
    subset = closed[closed["complaint_type"].isin(top_types)]
    table = subset.pivot_table(index="borough", columns="complaint_type",
                               values="closing_hours", aggfunc="median")
    return table[table.median().sort_values().index]


def fastest_type_per_borough(table: pd.DataFrame) -> pd.Series:
    return table.idxmin(axis=1)


def slowest_borough_counts(table: pd.DataFrame) -> pd.Series:
    return table.idxmax(axis=0).value_counts()


def compared_period(frame: pd.DataFrame) -> tuple:
    # first vs last calendar year, restricted to months present in both
    years = frame["year_month"].str[:4].astype(int)
    months = frame["year_month"].str[5:7].astype(int)
    all_years = sorted(years.unique())
    if len(all_years) < 2:
        raise ValueError("need at least two calendar years")
    previous_year, current_year = all_years[0], all_years[-1]
    shared = set(months[years == previous_year]) & set(months[years == current_year])
    return previous_year, current_year, sorted(shared)


def year_over_year(closed: pd.DataFrame, by: tuple = ("borough",)) -> pd.DataFrame:
    previous_year, current_year, shared_months = compared_period(closed)
    years = closed["year_month"].str[:4].astype(int)
    months = closed["year_month"].str[5:7].astype(int)
    keep = years.isin([previous_year, current_year]) & months.isin(shared_months)
    data = closed[keep].assign(year=years[keep])
    medians = data.groupby(list(by) + ["year"])["closing_hours"].median().unstack("year")
    medians = medians.rename(columns={previous_year: "median_previous",
                                      current_year: "median_current"})
    medians["change_pct"] = (medians["median_current"] / medians["median_previous"] - 1) * 100
    return medians.reset_index()


# ---------------------------------------------------------------
# Zip / borough consistency
# ---------------------------------------------------------------
def zip_borough_conflicts(frame: pd.DataFrame) -> pd.DataFrame:
    # zip codes that appear under more than one borough
    counts = frame.groupby(["incident_zip", "borough"]).size().reset_index(name="n")
    spread = counts.groupby("incident_zip")["borough"].nunique()
    conflicting = spread[spread > 1].index
    result = counts[counts["incident_zip"].isin(conflicting)]
    return result.sort_values(["incident_zip", "n"], ascending=[True, False])


def modal_borough_effect(cases: pd.DataFrame) -> dict:
    expected = cases["incident_zip"].map(modal_borough_by_zip(cases))
    changed = cases["borough"] != expected
    return {
        "rows_changed": int(changed.sum()),
        "share_changed_pct": round(float(changed.mean()) * 100, 4),
        "zip_codes_affected": int(cases.loc[changed, "incident_zip"].nunique()),
    }


# ---------------------------------------------------------------
# Population coverage
# ---------------------------------------------------------------
def population_coverage(cases: pd.DataFrame) -> dict:
    missing = cases["population"].isna()
    return {
        "rows": int(len(cases)),
        "rows_without_population": int(missing.sum()),
        "share_without_population_pct": round(float(missing.mean()) * 100, 4),
        "zip_codes_in_cases": int(cases["incident_zip"].nunique()),
        "zip_codes_without_population": int(cases.loc[missing, "incident_zip"].nunique()),
    }


# ---------------------------------------------------------------
# Sample vs total checks (live API)
# ---------------------------------------------------------------
def share_table(sample_counts: pd.Series, total_counts: pd.Series) -> pd.DataFrame:
    table = pd.DataFrame({"sample": sample_counts, "total": total_counts}).fillna(0)
    table["sample_share"] = table["sample"] / table["sample"].sum()
    table["total_share"] = table["total"] / table["total"].sum()
    table["abs_diff"] = (table["sample_share"] - table["total_share"]).abs()
    return table.sort_values("total", ascending=False)


def _window_where(config: Config, sampled: bool) -> str:
    clauses = [
        f"created_date >= '{config.start_date}T00:00:00'",
        f"created_date < '{config.end_date}T00:00:00'",
    ]
    if sampled and config.key_suffix_digits:
        likes = " OR ".join(f"unique_key like '%{d}'" for d in config.key_suffix_digits)
        clauses.append(f"({likes})")
    return " AND ".join(clauses)


def count_in_window(client: HttpClient, config: Config, sampled: bool) -> int:
    params = {"$select": "count(*) as n", "$where": _window_where(config, sampled)}
    return int(client.request_json(config.api_url, params)[0]["n"])


def fetch_group_counts(client: HttpClient, config: Config, expression: str) -> pd.Series:
    # server-side group count over the whole window (no sampling)
    params = {
        "$select": f"{expression} as grp, count(*) as n",
        "$where": _window_where(config, sampled=False),
        "$group": expression,
        "$limit": 50000,
    }
    rows = client.request_json(config.api_url, params)
    return pd.Series({row["grp"]: int(row["n"]) for row in rows if "grp" in row}).sort_index()


# ---------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------
DUPLICATE_CODES = [DUPLICATE_KEY, DUPLICATE_CONTENT]
DUPLICATE_PREVIEW_COLUMNS = [
    "unique_key", "created_date", "agency", "complaint_type",
    "incident_address", "reason_codes",
]


def duplicate_summary(manifest: dict) -> pd.DataFrame:
    reasons = manifest["records"]["quarantine_by_reason"]
    raw_count = manifest["records"]["raw"]
    rows = []
    for code in DUPLICATE_CODES:
        count = reasons.get(code, 0)
        rows.append({
            "reason": code,
            "rows": count,
            "share_of_raw_pct": round(count / raw_count * 100, 4) if raw_count else 0.0,
        })
    return pd.DataFrame(rows)


def duplicate_examples(quarantine_path, code: str, limit: int = 3) -> pd.DataFrame:
    frame = pd.read_csv(quarantine_path, dtype=str)
    subset = frame[frame["reason_codes"] == code]
    return subset[DUPLICATE_PREVIEW_COLUMNS].head(limit)


# ---------------------------------------------------------------
# Missing-value policy
# ---------------------------------------------------------------
# column -> missing-value policy (explained in the notebook and the report)
MISSING_POLICY = {
    "unique_key": "QUARANTINE",
    "created_date": "QUARANTINE",
    "agency": "QUARANTINE",
    "complaint_type": "QUARANTINE",
    "incident_zip": "QUARANTINE",
    "borough": "QUARANTINE",
    "closed_date": "KEEP_AS_OPEN_CASE",
    "closing_hours": "KEEP_EMPTY_OPEN_CASE",
    "descriptor": "FILL_UNKNOWN_LABEL",
    "incident_address": "KEEP_EMPTY",
    "community_board": "KEEP_EMPTY",
    "status": "KEEP_EMPTY",
    "resolution_description": "KEEP_EMPTY",
    "latitude": "KEEP_EMPTY",
    "longitude": "KEEP_EMPTY",
    "population": "KEEP_EMPTY_NO_RATE",
}


def missing_policy_table(cases: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column, policy in MISSING_POLICY.items():
        unknown_label = None
        if policy == "FILL_UNKNOWN_LABEL":
            unknown_label = round(float((cases[column] == "Unknown").mean()) * 100, 4)
        rows.append({
            "column": column,
            "policy": policy,
            "missing_pct": round(float(cases[column].isna().mean()) * 100, 4),
            "unknown_label_pct": unknown_label,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------
# Determinism check
# ---------------------------------------------------------------
def rerun_in_temp_dir(config: Config, client) -> dict:
    # same raw files, empty output folder: outputs are rebuilt from scratch
    with tempfile.TemporaryDirectory() as temp_dir:
        rerun_config = replace(config, curated_dir=temp_dir)
        return run_pipeline(rerun_config, client=client)


def compare_output_hashes(first: dict, second: dict) -> pd.DataFrame:
    rows = []
    for name in sorted(set(first) | set(second)):
        rows.append({
            "file": name,
            "hash_first": str(first.get(name, ""))[:16],
            "hash_second": str(second.get(name, ""))[:16],
            "identical": first.get(name) == second.get(name),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------
# Wide tables
# ---------------------------------------------------------------
WIDE_PREFIXES = ("median_hours_", "rate_per_10k_")


def wide_part(wide: pd.DataFrame, prefix: str) -> pd.DataFrame:
    id_columns = [column for column in wide.columns if not column.startswith(WIDE_PREFIXES)]
    metric_columns = [column for column in wide.columns if column.startswith(prefix)]
    return wide[id_columns + metric_columns]
