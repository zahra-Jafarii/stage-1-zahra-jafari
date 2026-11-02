"""Wide table: zip x complaint type, one column per month."""
import pandas as pd

from .config import Config

RATE_BASE = 10_000


def top_complaint_types(frame: pd.DataFrame, limit: int) -> list:
    counts = frame.groupby("complaint_type").size().reset_index(name="n")
    counts = counts.sort_values(["n", "complaint_type"], ascending=[False, True])
    return counts["complaint_type"].head(limit).tolist()


def build_wide_table(cases_path, config: Config) -> pd.DataFrame:
    columns = ["borough", "complaint_type", "year_month", "closing_hours", "population"]
    frame = pd.read_csv(cases_path, usecols=columns, dtype={"borough": str})
    frame = frame[frame["complaint_type"].isin(top_complaint_types(frame, config.top_complaint_types))]

    grouped = frame.groupby(["borough", "complaint_type", "year_month"]).agg(
        median_hours=("closing_hours", "median"),
        complaints=("closing_hours", "size"),
        population=("population", "first"),
    )
    safe_population = grouped["population"].where(grouped["population"] > 0)
    # sample counts are scaled back to full-city estimates
    grouped["rate_per_10k"] = grouped["complaints"] / config.sample_fraction / safe_population * RATE_BASE

    hours = grouped["median_hours"].unstack("year_month").sort_index(axis=1)
    rates = grouped["rate_per_10k"].unstack("year_month").sort_index(axis=1)
    hours.columns = [f"median_hours_{month}" for month in hours.columns]
    rates.columns = [f"rate_per_10k_{month}" for month in rates.columns]

    wide = pd.concat([hours, rates], axis=1).reset_index()
    population_by_borough = frame.groupby("borough")["population"].first()
    wide.insert(2, "population", wide["borough"].map(population_by_borough))
    return wide.sort_values(["borough", "complaint_type"]).reset_index(drop=True)