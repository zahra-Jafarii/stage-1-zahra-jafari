"""Orchestration: source -> validate -> clean -> enrich -> destinations -> report."""
import tracemalloc
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import Config, ensure_dir
from .exceptions import QuarantineThresholdError
from .files import write_json_atomic
from .manifest import build_manifest, utc_now_iso
from .quality_report import QualityProfiler
from .sinks import build_sinks
from .sources import build_source
from .transformer import DuplicateTracker, clean_batch, quarantine_frame, to_frame
from .validator import check_batch_types, check_required_columns, split_valid


@dataclass
class ProcessStats:
    raw_count: int = 0
    passed_count: int = 0
    quarantine_rows: int = 0
    reason_counts: Counter = field(default_factory=Counter)
    columns_seen: set = field(default_factory=set)


@dataclass
class RunFacts:
    """Everything the manifest needs besides the record counts."""
    started_at: str = ""
    finished_at: str = ""
    source: dict = field(default_factory=dict)
    destinations: list = field(default_factory=list)
    joins: dict = field(default_factory=dict)
    reference_checks: dict = field(default_factory=dict)
    reference_sources: dict = field(default_factory=dict)
    peak_memory_mb: float = None
    output_files: dict = field(default_factory=dict)


def count_reasons(frame: pd.DataFrame, stats: ProcessStats) -> None:
    for codes in frame["reason_codes"]:
        stats.reason_counts.update(codes.split("|"))
    stats.quarantine_rows += len(frame)


def process_batch(batch, dataset, contract, tracker, enrichers, stats,
                  curated_sink, quarantine_sink, profiler) -> None:
    check_batch_types(batch, contract)
    stats.raw_count += len(batch)
    stats.columns_seen.update(key for record in batch for key in record)

    valid, rejected = split_valid(batch, contract)
    frame, duplicates = tracker.split(to_frame(valid, contract.source_names))
    for quarantined in (quarantine_frame(rejected, contract), duplicates):
        if len(quarantined):
            count_reasons(quarantined, stats)
            quarantine_sink.write(quarantined)

    if frame.empty:  # nothing left to clean in this batch
        return
    cleaned = dataset.derive(clean_batch(frame, contract))
    for enricher in enrichers:
        cleaned = enricher.apply(cleaned)
    stats.passed_count += len(cleaned)
    profiler.update(cleaned)
    curated_sink.write(cleaned)


def check_quarantine_ratio(stats: ProcessStats, config: Config) -> None:
    ratio = stats.quarantine_rows / stats.raw_count if stats.raw_count else 0.0
    if ratio > config.quarantine_threshold:
        raise QuarantineThresholdError(
            f"quarantine ratio {ratio:.4f} is above threshold {config.quarantine_threshold}")


def process_stage(config, dataset, contract, source, engine=None) -> tuple:
    enrichers = dataset.build_enrichers(config)
    ensure_dir(config.curated_dir)
    curated_sink, quarantine_sink = build_sinks(config, contract, engine)
    stats, tracker = ProcessStats(), DuplicateTracker(contract)
    profiler = QualityProfiler(contract.output_names)
    try:
        for batch in source.iter_batches():
            process_batch(batch, dataset, contract, tracker, enrichers, stats,
                          curated_sink, quarantine_sink, profiler)
        check_required_columns(stats.columns_seen, contract)
        check_quarantine_ratio(stats, config)
    except Exception:
        curated_sink.abort()  # no suspicious dataset is published
        quarantine_sink.close()  # kept for inspection
        raise
    curated_sink.close()
    quarantine_sink.close()
    return stats, enrichers, profiler, curated_sink, quarantine_sink


def csv_outputs(config: Config) -> dict:
    curated_dir = Path(config.curated_dir)
    names = ("cases.csv", "quarantine.csv") if "csv" in config.destinations else ()
    return {name: curated_dir / name for name in names}


def write_derived_outputs(config, dataset, outputs, profiler, reference_checks) -> None:
    report_path = Path(config.curated_dir) / "quality_report.json"
    write_json_atomic(report_path, profiler.report(reference_checks))
    outputs["quality_report.json"] = report_path
    if dataset.build_extra_outputs:
        outputs.update(dataset.build_extra_outputs(config, outputs))


def collect_run_facts(config, dataset, source, enrichers, sinks, outputs) -> RunFacts:
    facts = RunFacts(source=source.describe(), output_files=outputs)
    facts.destinations = sinks[0].describe() + sinks[1].describe()
    facts.joins = {item.name: item.join_report() for item in enrichers}
    facts.reference_checks = {item.name: item.consistency_report()
                              for item in enrichers if item.compare}
    facts.reference_sources = dataset.describe_references(config)
    return facts


def run_pipeline(config: Config, do_fetch: bool = True, do_process: bool = True,
                 client=None, source=None, dataset=None, engine=None):
    """Run the factory. `source`, `dataset` and `engine` default to what the config says."""
    started_at = utc_now_iso()
    if dataset is None:  # bundled datasets are looked up by name only when none is passed
        from .datasets import get_dataset
        dataset = get_dataset(config.dataset)
    contract = dataset.build_contract(config)
    if config.track_memory:
        tracemalloc.start()
    source = source or build_source(config, contract.source_names, client)
    if do_process:
        dataset.prepare(config)

    if do_fetch:
        source.fetch()
    if not do_process:
        return None

    stats, enrichers, profiler, *sinks = process_stage(config, dataset, contract, source, engine)
    outputs = csv_outputs(config)
    reference_checks = {item.name: item.consistency_report()
                        for item in enrichers if item.compare}
    write_derived_outputs(config, dataset, outputs, profiler, reference_checks)

    facts = collect_run_facts(config, dataset, source, enrichers, sinks, outputs)
    facts.started_at, facts.finished_at = started_at, utc_now_iso()
    if config.track_memory:
        facts.peak_memory_mb = round(tracemalloc.get_traced_memory()[1] / 1e6, 1)
        tracemalloc.stop()
    manifest = build_manifest(config, stats, facts)
    write_json_atomic(Path(config.curated_dir) / "manifest_run.json", manifest)
    return manifest
