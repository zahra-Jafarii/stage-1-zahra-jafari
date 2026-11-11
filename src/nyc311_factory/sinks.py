"""Destinations. Data is staged first and published only on close()."""
import re
from pathlib import Path

import pandas as pd

from .exceptions import ConfigError, DestinationError

FLOAT_FORMAT = "%.4f"
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class CsvSink:
    """Atomic CSV writer: data goes to .tmp and is renamed on close."""

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

    def describe(self) -> dict:
        return {"type": "csv", "file": self.path.name}


def check_identifier(name: str) -> str:
    if not IDENTIFIER.fullmatch(name):
        raise ConfigError(f"bad database name: {name!r}")
    return name


def quote_name(schema: str, name: str) -> str:
    parts = [part for part in (schema, name) if part]
    return ".".join(f'"{check_identifier(part)}"' for part in parts)


class DatabaseSink:
    """SQL table writer. Batches go to a staging table; close() swaps it in.

    A failed or repeated run never leaves a half-written table and never
    duplicates rows: the target table is replaced as a whole.
    """

    def __init__(self, engine, table: str, columns: list, schema: str = "",
                 dtypes: dict = None, chunk_rows: int = 10_000, mode: str = "replace"):
        self.engine = engine
        self.table = check_identifier(table)
        self.schema = schema
        self.columns = columns
        self.dtypes = dtypes
        self.chunk_rows = chunk_rows
        self.mode = mode
        self.staging = f"{self.table}__staging"
        self.rows_written = 0
        self.prepared = False

    def _run(self, *statements: str) -> None:
        from sqlalchemy import text
        with self.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

    def _prepare(self) -> None:
        if self.schema:
            self._run(f'CREATE SCHEMA IF NOT EXISTS "{check_identifier(self.schema)}"')
        self._run(f"DROP TABLE IF EXISTS {quote_name(self.schema, self.staging)}")
        self.prepared = True

    def _append(self, frame: pd.DataFrame) -> None:
        with self.engine.begin() as connection:
            frame.to_sql(self.staging, connection, schema=self.schema or None,
                         if_exists="append", index=False, dtype=self.dtypes,
                         chunksize=self.chunk_rows)

    def write(self, frame: pd.DataFrame) -> None:
        frame = frame.reindex(columns=self.columns)
        try:
            if not self.prepared:
                self._prepare()
            self._append(frame)
        except Exception as error:
            raise DestinationError(f"cannot write table {self.table}: {error}") from error
        self.rows_written += len(frame)

    def close(self) -> None:
        try:
            if not self.prepared:  # empty output still gets a table
                self._prepare()
                self._append(pd.DataFrame(columns=self.columns))
            self._run(*self._publish_statements())
        except Exception as error:
            raise DestinationError(f"cannot publish table {self.table}: {error}") from error

    def _publish_statements(self) -> tuple:
        target = quote_name(self.schema, self.table)
        staging = quote_name(self.schema, self.staging)
        if self.mode == "existing":
            # keep the table you created (keys, indexes, views); only its rows are reloaded
            names = ", ".join(f'"{check_identifier(name)}"' for name in self.columns)
            return (f"DELETE FROM {target}",
                    f"INSERT INTO {target} ({names}) SELECT {names} FROM {staging}",
                    f"DROP TABLE {staging}")
        return (f"DROP TABLE IF EXISTS {target}",
                f'ALTER TABLE {staging} RENAME TO "{self.table}"')

    def abort(self) -> None:
        if not self.prepared:
            return
        try:
            self._run(f"DROP TABLE IF EXISTS {quote_name(self.schema, self.staging)}")
        except Exception:
            pass  # the next run drops a leftover staging table anyway

    def describe(self) -> dict:
        name = f"{self.schema}.{self.table}" if self.schema else self.table
        return {"type": "database", "table": name, "rows_written": self.rows_written}


class MultiSink:
    """Sends every batch to several destinations."""

    def __init__(self, sinks: list):
        self.sinks = sinks

    def write(self, frame: pd.DataFrame) -> None:
        for sink in self.sinks:
            sink.write(frame)

    def close(self) -> None:
        for sink in self.sinks:
            sink.close()

    def abort(self) -> None:
        for sink in self.sinks:
            sink.abort()

    def describe(self) -> list:
        return [sink.describe() for sink in self.sinks]


def sqlalchemy_types(columns: list) -> dict:
    # contract dtype -> SQL column type
    from sqlalchemy import types
    mapping = {
        "str": types.Text(), "zip5": types.String(5), "datetime": types.DateTime(),
        "float": types.Float(), "int": types.BigInteger(), "bool": types.Boolean(),
    }
    return {column.name: mapping[column.dtype] for column in columns}


def build_engine(config):
    import os
    url = os.environ.get(config.database_url_env)
    if not url:
        raise ConfigError(f"environment variable {config.database_url_env} is not set")
    try:
        from sqlalchemy import create_engine
    except ImportError as error:
        raise ConfigError("SQLAlchemy is not installed") from error
    return create_engine(url)


def build_sinks(config, contract, engine=None) -> tuple:
    """Return (curated_sink, quarantine_sink) for the destinations in the config."""
    curated_dir = Path(config.curated_dir)
    curated, quarantine = [], []
    if "csv" in config.destinations:
        curated.append(CsvSink(curated_dir / "cases.csv", contract.output_names))
        quarantine.append(CsvSink(curated_dir / "quarantine.csv", contract.quarantine_names))
    if "database" in config.destinations:
        engine = engine or build_engine(config)
        types = sqlalchemy_types(contract.output_columns)
        # default table names come from the contract, so two datasets never share a table
        cases_table = config.database_cases_table or contract.name
        quarantine_table = config.database_quarantine_table or f"{contract.name}_quarantine"
        curated.append(DatabaseSink(engine, cases_table, contract.output_names,
                                    config.database_schema, types,
                                    mode=config.database_load_mode))
        quarantine.append(DatabaseSink(engine, quarantine_table,
                                       contract.quarantine_names, config.database_schema,
                                       mode=config.database_load_mode))
    return MultiSink(curated), MultiSink(quarantine)
