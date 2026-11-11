"""Socrata API source: monthly raw files with a checkpoint, read back as batches."""
from typing import Iterator

from .config import Config
from .fetcher import Checkpoint, fetch_all, plan_partitions, raw_paths
from .http_client import HttpClient
from .sources import JsonlSource, RecordSource


class ApiSource(RecordSource):
    """Socrata API: monthly raw files with checkpoint, then read back as batches."""
    kind = "api"

    def __init__(self, config: Config, client: HttpClient, columns: list):
        self.config = config
        self.client = client
        self.columns = columns
        self.partitions = plan_partitions(config.start, config.end)
        self.checkpoint = Checkpoint(config, columns)
        self.summary = {"fetched": 0, "reused": 0}

    def fetch(self) -> dict:
        self.summary = fetch_all(self.client, self.config, self.partitions,
                                 self.checkpoint, self.columns)
        return self.summary

    def iter_batches(self) -> Iterator[list]:
        paths = raw_paths(self.config, self.partitions, self.checkpoint)
        yield from JsonlSource(paths, self.config.page_size).iter_batches()

    def describe(self) -> dict:
        return {
            "type": self.kind,
            "url": self.config.api_url,
            "requests": self.client.request_count,
            "partitions_fetched": self.summary["fetched"],
            "partitions_reused": self.summary["reused"],
            "sampling": {
                "key_suffix_digits": list(self.config.key_suffix_digits),
                "sample_fraction": self.config.sample_fraction,
            },
        }
