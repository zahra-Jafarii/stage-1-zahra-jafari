"""Record sources. Pipeline only sees batches of dicts."""
import json
from abc import ABC, abstractmethod
from typing import Iterator

from .exceptions import DataValidationError


class RecordSource(ABC):
    @abstractmethod
    def iter_batches(self) -> Iterator[list]:
        """Yield lists of raw record dicts."""


class JsonlSource(RecordSource):
    def __init__(self, paths: list, batch_size: int):
        self.paths = paths
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