"""Atomic CSV writer: data goes to .tmp and is renamed on close."""
from pathlib import Path

import pandas as pd

FLOAT_FORMAT = "%.4f"


class CsvSink:
    def __init__(self, path: Path, columns: list):
        self.path = Path(path)
        self.tmp_path = self.path.with_name(self.path.name + ".tmp")
        self.columns = columns
        self.handle = open(self.tmp_path, "w", encoding="utf-8", newline="")
        self.header_written = False

    def write(self, frame: pd.DataFrame) -> None:
        frame = frame.reindex(columns=self.columns)
        frame.to_csv(self.handle, index=False, header=not self.header_written,
                     float_format=FLOAT_FORMAT, lineterminator="\n")
        self.header_written = True

    def close(self) -> None:
        if not self.header_written:  # empty output still gets a header
            self.write(pd.DataFrame(columns=self.columns))
        self.handle.close()
        self.tmp_path.replace(self.path)

    def abort(self) -> None:
        self.handle.close()
        self.tmp_path.unlink(missing_ok=True)