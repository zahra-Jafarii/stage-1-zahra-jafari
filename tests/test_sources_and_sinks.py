import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from nyc311_factory.exceptions import ConfigError, DataValidationError
from nyc311_factory.sinks import CsvSink, DatabaseSink, MultiSink, quote_name
from nyc311_factory.api_source import ApiSource
from nyc311_factory.sources import CsvSource, JsonlSource, build_source
from tests.helpers import FakeClient, make_config

try:
    import sqlalchemy
except ImportError:
    sqlalchemy = None


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_csv_source_yields_text_batches(self):
        path = self.write("data.csv", "a,b\n1,x\n2,\n3,z\n")
        batches = list(CsvSource(path, batch_size=2).iter_batches())
        self.assertEqual([len(batch) for batch in batches], [2, 1])
        self.assertEqual(batches[0][1], {"a": "2", "b": ""})  # empty cell stays empty text

    def test_csv_source_reports_missing_file(self):
        with self.assertRaises(ConfigError):
            list(CsvSource(self.root / "nope.csv", 10).iter_batches())

    def test_jsonl_source_rejects_corrupt_line(self):
        path = self.write("raw.jsonl", '{"a": 1}\nnot json\n')
        with self.assertRaises(DataValidationError):
            list(JsonlSource([path], 10).iter_batches())

    def test_jsonl_source_batches_across_files(self):
        first = self.write("one.jsonl", json.dumps({"a": 1}) + "\n")
        second = self.write("two.jsonl", json.dumps({"a": 2}) + "\n")
        batches = list(JsonlSource([first, second], batch_size=5).iter_batches())
        self.assertEqual(batches, [[{"a": 1}, {"a": 2}]])

    def test_build_source_follows_source_type(self):
        columns = ["unique_key"]
        self.assertIsInstance(build_source(make_config(), columns, FakeClient([])), ApiSource)
        csv_config = make_config(source_type="csv", input_path="x.csv")
        self.assertIsInstance(build_source(csv_config, columns), CsvSource)
        jsonl_config = make_config(source_type="jsonl", input_path="x.jsonl")
        self.assertIsInstance(build_source(jsonl_config, columns), JsonlSource)

    def test_file_source_needs_input_path(self):
        from nyc311_factory.config import validate_config
        with self.assertRaises(ConfigError):
            validate_config(make_config(source_type="csv", input_path=""))


class CsvSinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "out.csv"

    def test_file_appears_only_on_close(self):
        sink = CsvSink(self.path, ["a"])
        sink.write(pd.DataFrame({"a": [1]}))
        self.assertFalse(self.path.exists())
        sink.close()
        self.assertTrue(self.path.exists())

    def test_abort_leaves_no_file(self):
        sink = CsvSink(self.path, ["a"])
        sink.write(pd.DataFrame({"a": [1]}))
        sink.abort()
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_empty_output_still_has_header(self):
        CsvSink(self.path, ["a", "b"]).close()
        self.assertEqual(self.path.read_text(encoding="utf-8").strip(), "a,b")

    def test_multi_sink_writes_everywhere(self):
        other = self.path.with_name("other.csv")
        sink = MultiSink([CsvSink(self.path, ["a"]), CsvSink(other, ["a"])])
        sink.write(pd.DataFrame({"a": [1]}))
        sink.close()
        self.assertTrue(self.path.exists() and other.exists())


class DatabaseNamesTest(unittest.TestCase):
    def test_names_are_quoted(self):
        self.assertEqual(quote_name("stage1", "cases"), '"stage1"."cases"')
        self.assertEqual(quote_name("", "cases"), '"cases"')

    def test_unsafe_name_is_rejected(self):
        with self.assertRaises(ConfigError):
            quote_name("", "cases; DROP TABLE x")


@unittest.skipIf(sqlalchemy is None, "SQLAlchemy is not installed")
class DatabaseSinkTest(unittest.TestCase):
    def setUp(self):
        self.engine = sqlalchemy.create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

    def tables(self):
        with self.engine.connect() as connection:
            query = sqlalchemy.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            return {row[0] for row in connection.execute(query)}

    def count_rows(self, table):
        with self.engine.connect() as connection:
            return connection.execute(sqlalchemy.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()

    def test_table_appears_only_on_close(self):
        sink = DatabaseSink(self.engine, "cases", ["a"])
        sink.write(pd.DataFrame({"a": [1, 2]}))
        self.assertEqual(self.tables(), {"cases__staging"})
        sink.close()
        self.assertEqual(self.tables(), {"cases"})
        self.assertEqual(self.count_rows("cases"), 2)

    def test_abort_keeps_the_previous_table(self):
        first = DatabaseSink(self.engine, "cases", ["a"])
        first.write(pd.DataFrame({"a": [1]}))
        first.close()
        second = DatabaseSink(self.engine, "cases", ["a"])
        second.write(pd.DataFrame({"a": [7, 8, 9]}))
        second.abort()
        self.assertEqual(self.tables(), {"cases"})
        self.assertEqual(self.count_rows("cases"), 1)

    def test_empty_output_still_creates_the_table(self):
        DatabaseSink(self.engine, "cases", ["a", "b"]).close()
        self.assertEqual(self.count_rows("cases"), 0)

    def test_rerun_replaces_the_table(self):
        for _ in range(2):
            sink = DatabaseSink(self.engine, "cases", ["a"])
            sink.write(pd.DataFrame({"a": [1, 2, 3]}))
            sink.close()
        self.assertEqual(self.count_rows("cases"), 3)

    def test_existing_mode_keeps_the_table_and_reloads_rows(self):
        with self.engine.begin() as connection:
            connection.execute(sqlalchemy.text('CREATE TABLE "cases" (a INTEGER PRIMARY KEY)'))
            connection.execute(sqlalchemy.text('INSERT INTO "cases" VALUES (99)'))
        for _ in range(2):
            sink = DatabaseSink(self.engine, "cases", ["a"], mode="existing")
            sink.write(pd.DataFrame({"a": [1, 2]}))
            sink.close()
        self.assertEqual(self.count_rows("cases"), 2)  # old row gone, no duplicates
        self.assertEqual(self.tables(), {"cases"})

    def test_existing_mode_fails_when_the_table_is_missing(self):
        from nyc311_factory.exceptions import DestinationError
        sink = DatabaseSink(self.engine, "cases", ["a"], mode="existing")
        sink.write(pd.DataFrame({"a": [1]}))
        with self.assertRaises(DestinationError):
            sink.close()
