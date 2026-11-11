"""Record sources. The pipeline only sees batches of dicts."""
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

import pandas as pd

from .config import Config
from .exceptions import ConfigError, DataValidationError
from .files import sha256_file


class RecordSource(ABC):
    kind = "source"

    def fetch(self) -> dict:
        """Download step. Sources that already have their data do nothing."""
        return {}

    @abstractmethod
    def iter_batches(self) -> Iterator[list]:
        """Yield lists of raw record dicts."""

    def describe(self) -> dict:
        """Facts about the input, written to the run manifest."""
        return {"type": self.kind}


class JsonlSource(RecordSource):
    kind = "jsonl"

    def __init__(self, paths: list, batch_size: int):
        self.paths = [Path(path) for path in paths]
        self.batch_size = batch_size

    def iter_batches(self) -> Iterator[list]:
        batch = []
        for path in self.paths:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    batch.append(self._parse(line, path))
                    if len(batch) >= self.batch_size:
                        yield batch
                        batch = []
        if batch:
            yield batch

    @staticmethod
    def _parse(line: str, path) -> dict:
        try:
            return json.loads(line)
        except json.JSONDecodeError as error:
            raise DataValidationError(f"corrupt raw line in {path}") from error

    def describe(self) -> dict:
        return {"type": self.kind, "files": [path.name for path in self.paths]}


class CsvSource(RecordSource):
    """Reads a csv file in chunks. Every value stays text; empty cells stay empty text."""
    kind = "csv"

    def __init__(self, path: str, batch_size: int):
        self.path = Path(path)
        self.batch_size = batch_size

    def iter_batches(self) -> Iterator[list]:
        if not self.path.is_file():
            raise ConfigError(f"input file not found: {self.path}")
        try:
            chunks = pd.read_csv(self.path, dtype=str, na_filter=False,
                                 chunksize=self.batch_size, encoding="utf-8")
            for chunk in chunks:
                yield chunk.to_dict("records")
        except (pd.errors.ParserError, UnicodeDecodeError) as error:
            raise DataValidationError(f"corrupt csv {self.path}: {error}") from error

    def describe(self) -> dict:
        digest = sha256_file(self.path) if self.path.is_file() else None
        return {"type": self.kind, "file": self.path.name, "sha256": digest}


def build_source(config: Config, columns: list, client=None) -> RecordSource:
    if config.source_type == "api":
        from .api_source import ApiSource  # loaded only when the api source is used
        from .http_client import HttpClient
        return ApiSource(config, client or HttpClient(config), columns)
    if config.source_type == "csv":
        return CsvSource(config.input_path, config.page_size)
    if config.source_type == "jsonl":
        return JsonlSource([config.input_path], config.page_size)
    raise ConfigError(f"unknown source_type: {config.source_type}")
