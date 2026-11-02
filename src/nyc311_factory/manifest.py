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


def build_manifest(config: Config, stats, fetch_summary: dict, request_count: int,
                   started_at: str, finished_at: str, peak_memory_mb, output_files: dict) -> dict:
    return {
        "code_version": git_version(),
        "started_at": started_at,
        "finished_at": finished_at,
        "window": {"start": config.start_date, "end": config.end_date},
        "sampling": {
            "key_suffix_digits": list(config.key_suffix_digits),
            "sample_fraction": config.sample_fraction,
        },
        "records": {
            "raw": stats.raw_count,
            "passed": stats.passed_count,
            "quarantined_rows": stats.quarantine_rows,
            "quarantine_by_reason": dict(sorted(stats.reason_counts.items())),
        },
        "population_join": {
            "rows_before": stats.join_rows_before,
            "rows_after": stats.join_rows_after,
        },
        "http": {
            "requests": request_count,
            "partitions_fetched": fetch_summary["fetched"],
            "partitions_reused": fetch_summary["reused"],
        },
        "peak_memory_mb": peak_memory_mb,
        "output_hashes": {name: sha256_file(path) for name, path in sorted(output_files.items())},
    }