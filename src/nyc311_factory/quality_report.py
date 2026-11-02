"""Auto-generated data quality report for the curated cases."""
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype


def describe_column(series: pd.Series) -> dict:
    info = {
        "pct_missing": round(float(series.isna().mean()) * 100, 4),
        "n_unique": int(series.nunique()),
    }
    if series.dropna().empty:
        return info
    if is_numeric_dtype(series) and series.dtype != bool:
        info["range"] = [float(series.min()), float(series.max())]
    elif is_datetime64_any_dtype(series):
        info["range"] = [str(series.min()), str(series.max())]
    else:
        info["top_value"] = str(series.mode().iloc[0])
    return info


def build_quality_report(cases_path) -> dict:
    frame = pd.read_csv(
        cases_path, dtype={"incident_zip": str, "unique_key": str},
        parse_dates=["created_date", "closed_date"],
    )
    report = {column: describe_column(frame[column]) for column in frame.columns}
    return {"rows": len(frame), "columns": report}