"""Batch download into monthly raw files with checkpoint and resume."""
import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import Config, ensure_dir
from .exceptions import DataValidationError, InvalidResponseError
from .files import sha256_file
from .http_client import HttpClient


@dataclass(frozen=True)
class Partition:
    name: str
    start: date
    end: date  # exclusive


def plan_partitions(start: date, end: date) -> list:
    partitions = []
    current = start
    while current < end:
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        stop = min(next_month, end)
        partitions.append(Partition(current.strftime("%Y-%m"), current, stop))
        current = stop
    return partitions


def partition_path(raw_dir: str, partition: Partition) -> Path:
    return Path(raw_dir) / f"part_{partition.name}.jsonl"


def filter_signature(config: Config, columns: list) -> str:
    # checkpoint is valid only for the same source, filter and column list
    payload = [config.api_url, list(config.key_suffix_digits), list(columns)]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


class Checkpoint:
    def __init__(self, config: Config, columns: list):
        self.raw_dir = config.raw_dir
        self.path = Path(config.raw_dir) / "_checkpoint.json"
        self.signature = filter_signature(config, columns)
        self.partitions = {}
        self._load()
    #  وضعیت های قبلی رو از روی دیسک میخونه.فایل checkpoint
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return  # corrupt file: start over
        if data.get("signature") == self.signature:
            self.partitions = data.get("partitions", {})

    def _save(self) -> None:
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        data = {"signature": self.signature, "partitions": self.partitions}
        tmp_path.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def is_complete(self, partition: Partition) -> bool:
        entry = self.partitions.get(partition.name)
        path = partition_path(self.raw_dir, partition)
        if not entry or not path.exists():
            return False
        same_window = (entry["start"], entry["end"]) == (
            partition.start.isoformat(), partition.end.isoformat())
        return same_window and entry["sha256"] == sha256_file(path)

    def mark_done(self, partition: Partition, rows: int, sha256: str) -> None:
        self.partitions[partition.name] = {
            "start": partition.start.isoformat(),
            "end": partition.end.isoformat(),
            "rows": rows,
            "sha256": sha256,
        }
        self._save()


def build_params(config: Config, partition: Partition, last_key, columns: list) -> dict:
    clauses = [
        f"created_date >= '{partition.start.isoformat()}T00:00:00'",
        f"created_date < '{partition.end.isoformat()}T00:00:00'",
    ]
    if config.key_suffix_digits:
        likes = " OR ".join(f"unique_key like '%{d}'" for d in config.key_suffix_digits)
        clauses.append(f"({likes})")
    if last_key:
        clauses.append(f"unique_key > '{last_key}'")
    return {
        "$select": ",".join(columns),
        "$where": " AND ".join(clauses),
        "$order": "unique_key",
        "$limit": config.page_size,
    }


def check_page(page, last_key) -> None:
    if not isinstance(page, list):
        raise InvalidResponseError("page is not a JSON list")
    for record in page:
        if not isinstance(record, dict) or "unique_key" not in record:
            raise InvalidResponseError("record without unique_key")
    if page and last_key and page[0]["unique_key"] <= last_key:
        raise InvalidResponseError("keyset did not advance")


def fetch_partition(client: HttpClient, config: Config, partition: Partition, columns: list) -> tuple:
    final_path = partition_path(config.raw_dir, partition)
    tmp_path = final_path.with_name(final_path.name + ".tmp")
    last_key, rows = None, 0
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
        while True:
            page = client.request_json(config.api_url, build_params(config, partition, last_key, columns))
            check_page(page, last_key)
            for record in page:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            rows += len(page)
            if len(page) < config.page_size:
                break
            last_key = page[-1]["unique_key"]
    tmp_path.replace(final_path)  # atomic: half-written files are never final
    return rows, sha256_file(final_path)


def fetch_all(client: HttpClient, config: Config, partitions: list,
              checkpoint: Checkpoint, columns: list) -> dict:
    ensure_dir(config.raw_dir)
    summary = {"fetched": 0, "reused": 0}
    for partition in partitions:
        if checkpoint.is_complete(partition):
            summary["reused"] += 1
            continue
        rows, sha256 = fetch_partition(client, config, partition, columns)
        checkpoint.mark_done(partition, rows, sha256)
        summary["fetched"] += 1
    return summary


def raw_paths(config: Config, partitions: list, checkpoint: Checkpoint) -> list:
    # every partition must be fetched completely before processing starts
    paths = []
    for partition in partitions:
        if not checkpoint.is_complete(partition):
            raise DataValidationError(f"raw partition {partition.name} missing; run fetch first")
        paths.append(partition_path(config.raw_dir, partition))
    return paths
