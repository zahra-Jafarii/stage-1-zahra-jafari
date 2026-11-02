"""Orchestration: fetch -> validate -> transform -> write -> report."""
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

import pandas as pd

from .aggregate import build_wide_table
from .config import Config, ensure_dir
from .exceptions import DataValidationError, QuarantineThresholdError
from .fetcher import Checkpoint, fetch_all, partition_path, plan_partitions
from .files import write_json_atomic
from .http_client import HttpClient
from .manifest import build_manifest, utc_now_iso
from .quality_report import build_quality_report
from .schema import CURATED_COLUMNS, QUARANTINE_COLUMNS
from .sinks import CsvSink
from .sources import JsonlSource
from .transformer import (
    DuplicateTracker, attach_population, clean_batch, load_population,
    quarantine_frame, to_frame,
)
from .validator import check_batch_types, check_required_columns, split_valid


@dataclass
class ProcessStats:
    raw_count: int = 0
    passed_count: int = 0
    quarantine_rows: int = 0
    reason_counts: Counter = field(default_factory=Counter)
    join_rows_before: int = 0
    join_rows_after: int = 0
    columns_seen: set = field(default_factory=set)


def count_reasons(frame: pd.DataFrame, stats: ProcessStats) -> None:
    for codes in frame["reason_codes"]:
        stats.reason_counts.update(codes.split("|"))
    stats.quarantine_rows += len(frame)


def process_batch(batch, window, tracker, population, stats, curated_sink, quarantine_sink):
    check_batch_types(batch)
    stats.raw_count += len(batch)
    stats.columns_seen.update(key for record in batch for key in record)

    valid, rejected = split_valid(batch, *window)
    frame, duplicates = tracker.split(to_frame(valid))
    for quarantined in (quarantine_frame(rejected), duplicates):
        if len(quarantined):
            count_reasons(quarantined, stats)
            quarantine_sink.write(quarantined)

    if frame.empty:  # nothing left to clean in this batch
        return
    cleaned = clean_batch(frame)
    stats.join_rows_before += len(cleaned)
    cleaned = attach_population(cleaned, population)
    stats.join_rows_after += len(cleaned)
    stats.passed_count += len(cleaned)
    curated_sink.write(cleaned)


def check_quarantine_ratio(stats: ProcessStats, config: Config) -> None:
    ratio = stats.quarantine_rows / stats.raw_count if stats.raw_count else 0.0
    if ratio > config.quarantine_threshold:
        raise QuarantineThresholdError(
            f"quarantine ratio {ratio:.4f} is above threshold {config.quarantine_threshold}")


def raw_paths(config: Config, partitions: list, checkpoint: Checkpoint) -> list:
    paths = []
    for partition in partitions:
        if not checkpoint.is_complete(partition):
            raise DataValidationError(f"raw partition {partition.name} missing; run fetch first")
        paths.append(partition_path(config.raw_dir, partition))
    return paths


def process_stage(config: Config, partitions: list, checkpoint: Checkpoint) -> tuple:
    paths = raw_paths(config, partitions, checkpoint)
    population = load_population(config)
    window = (datetime.combine(config.start, time.min), datetime.combine(config.end, time.min))
    curated_dir = ensure_dir(config.curated_dir)
    cases_path = curated_dir / "cases.csv"
    quarantine_path = curated_dir / "quarantine.csv"

    curated_sink = CsvSink(cases_path, CURATED_COLUMNS)
    quarantine_sink = CsvSink(quarantine_path, QUARANTINE_COLUMNS)
    stats, tracker = ProcessStats(), DuplicateTracker()
    try:
        for batch in JsonlSource(paths, config.page_size).iter_batches():
            process_batch(batch, window, tracker, population, stats, curated_sink, quarantine_sink)
        check_required_columns(stats.columns_seen)
        check_quarantine_ratio(stats, config)
    except Exception:
        curated_sink.abort()  # no suspicious dataset is published
        quarantine_sink.close()  # kept for inspection
        raise
    curated_sink.close()
    quarantine_sink.close()
    return stats, {"cases.csv": cases_path, "quarantine.csv": quarantine_path}


def write_derived_outputs(config: Config, outputs: dict) -> None:
    curated_dir = Path(config.curated_dir)
    wide = build_wide_table(outputs["cases.csv"], config)
    wide_path = curated_dir / "aggregate_wide.csv"
    sink = CsvSink(wide_path, list(wide.columns))
    sink.write(wide)
    sink.close()
    outputs["aggregate_wide.csv"] = wide_path

    report_path = curated_dir / "quality_report.json"
    write_json_atomic(report_path, build_quality_report(outputs["cases.csv"]))
    outputs["quality_report.json"] = report_path


def run_pipeline(config: Config, do_fetch: bool = True, do_process: bool = True, client=None):
    started_at = utc_now_iso()
    if config.track_memory:
        tracemalloc.start()
    client = client or HttpClient(config)
    partitions = plan_partitions(config.start, config.end)
    checkpoint = Checkpoint(config)

    fetch_summary = {"fetched": 0, "reused": 0}
    if do_fetch:
        fetch_summary = fetch_all(client, config, partitions, checkpoint)
    if not do_process:
        return None

    stats, outputs = process_stage(config, partitions, checkpoint)
    write_derived_outputs(config, outputs)

    peak_mb = None
    if config.track_memory:
        peak_mb = round(tracemalloc.get_traced_memory()[1] / 1e6, 1)
        tracemalloc.stop()
    manifest = build_manifest(config, stats, fetch_summary, client.request_count,
                              started_at, utc_now_iso(), peak_mb, outputs)
    write_json_atomic(Path(config.curated_dir) / "manifest_run.json", manifest)
    return manifest