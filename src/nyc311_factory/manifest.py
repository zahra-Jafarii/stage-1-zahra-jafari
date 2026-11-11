"""Run manifest: counts, window, version, hashes."""
import subprocess
from datetime import datetime, timezone

from .config import Config
from .files import sha256_file


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_version() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("nyc311-factory")
    except PackageNotFoundError:
        return "unknown"


def build_manifest(config: Config, stats, run) -> dict:
    """`run` is a RunFacts object from the pipeline (source, joins, destinations, times)."""
    return {
        "code_version": git_version(),  # commit of the project that runs the factory
        "package_version": package_version(),
        "dataset": config.dataset,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "window": {"start": config.start_date, "end": config.end_date} if config.start_date else None,
        "source": run.source,
        "destinations": run.destinations,
        "records": {
            "raw": stats.raw_count,
            "passed": stats.passed_count,
            "quarantined_rows": stats.quarantine_rows,
            "quarantine_by_reason": dict(sorted(stats.reason_counts.items())),
        },
        "joins": run.joins,
        "reference_checks": run.reference_checks,
        "reference_sources": run.reference_sources,
        "peak_memory_mb": run.peak_memory_mb,
        "output_hashes": {name: sha256_file(path) for name, path in sorted(run.output_files.items())},
    }
