"""Wide table: borough x complaint type, one column per month."""
import pandas as pd

from .config import Config

RATE_BASE = 10_000


def top_complaint_types(frame: pd.DataFrame, limit: int) -> list:
    counts = frame.groupby("complaint_type").size().reset_index(name="n")
    counts = counts.sort_values(["n", "complaint_type"], ascending=[False, True])
    return counts["complaint_type"].head(limit).tolist()


def modal_borough_by_zip(cases: pd.DataFrame) -> pd.Series:
    # a zip code belongs to the borough it appears under most often
    return cases.groupby("incident_zip")["borough"].agg(lambda values: values.mode().iloc[0])


def borough_wide_table(cases: pd.DataFrame, sample_fraction: float, top_n: int) -> pd.DataFrame:
    # borough x complaint type rows, one column per month
    frame = cases.assign(borough=cases["incident_zip"].map(modal_borough_by_zip(cases)))
    frame = frame[frame["complaint_type"].isin(top_complaint_types(frame, top_n))]
    keys = ["borough", "complaint_type", "year_month"]

    medians = frame.groupby(keys)["closing_hours"].median()

    covered = frame[frame["population"].notna()]  # rates only count zips with a population
    zip_population = covered.groupby("incident_zip").agg(
        borough=("borough", "first"), population=("population", "first"))
    borough_population = zip_population.groupby("borough")["population"].sum()
    counts = covered.groupby(keys).size().rename("complaints").reset_index()
    # sample counts are scaled back to full-city estimates
    counts["rate_per_10k"] = (
        counts["complaints"] / sample_fraction
        / counts["borough"].map(borough_population) * RATE_BASE
    )
    rates = counts.set_index(keys)["rate_per_10k"]

    hours_wide = medians.unstack("year_month").sort_index(axis=1)
    rates_wide = rates.unstack("year_month").sort_index(axis=1)
    hours_wide.columns = [f"median_hours_{month}" for month in hours_wide.columns]
    rates_wide.columns = [f"rate_per_10k_{month}" for month in rates_wide.columns]
    wide = pd.concat([hours_wide, rates_wide], axis=1).reset_index()
    wide.insert(2, "population", wide["borough"].map(borough_population))
    return wide.sort_values(["borough", "complaint_type"]).reset_index(drop=True)


def build_wide_table(cases_path, config: Config) -> pd.DataFrame:
    columns = ["borough", "incident_zip", "complaint_type", "year_month",
               "closing_hours", "population"]
    cases = pd.read_csv(cases_path, usecols=columns, dtype={"borough": str, "incident_zip": str})
    return borough_wide_table(cases, config.sample_fraction, config.top_complaint_types)
