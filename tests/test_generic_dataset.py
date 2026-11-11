"""A dataset that is not NYC 311, run through the same factory (csv in, csv or database out)."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from nyc311_factory.contract import Column, Contract, check_contract
from nyc311_factory.dataset import Dataset
from nyc311_factory.exceptions import (
    ConfigError, QuarantineThresholdError, SchemaDriftError,
)
from nyc311_factory.pipeline import run_pipeline
from nyc311_factory.rules import not_before_rule
from tests.helpers import make_config

try:
    import sqlalchemy
except ImportError:
    sqlalchemy = None

HEADER = "order_id,amount,status,ordered_at,shipped_at\n"
ROWS = [
    "1,10.5,new,2024-01-01T10:00:00,",
    "2,20,DONE,2024-01-02T10:00:00,2024-01-03T10:00:00",
    "3,-5,NEW,2024-01-02T11:00:00,",                       # negative amount
    "4,7,LOST,2024-01-02T12:00:00,",                       # status not allowed
    "5,8,NEW,2024-01-04T10:00:00,2024-01-01T10:00:00",     # shipped before ordered
    "1,10.5,new,2024-01-01T10:00:00,",                     # same key again
]

ORDERS_CONTRACT = Contract(
    name="orders",
    source_columns=(
        Column("order_id", "str", nullable=False, missing_code="MISSING_ID"),
        Column("amount", "float", nullable=False, min_value=0,
               missing_code="BAD_AMOUNT", invalid_code="BAD_AMOUNT"),
        Column("status", "str", nullable=False, allowed=frozenset({"NEW", "DONE"}),
               case_insensitive=True, invalid_code="BAD_STATUS"),
        Column("ordered_at", "datetime", nullable=False,
               missing_code="BAD_ORDER_DATE", invalid_code="BAD_ORDER_DATE"),
        Column("shipped_at", "datetime", invalid_code="BAD_SHIP_DATE"),
    ),
    derived_columns=(),
    key_column="order_id",
    content_columns=("amount", "status", "ordered_at"),
    required_columns=("order_id", "amount", "status"),
    row_rules=(not_before_rule("ordered_at", "shipped_at", "SHIPPED_BEFORE_ORDERED"),),
)
ORDERS = Dataset(name="orders", build_contract=lambda config: ORDERS_CONTRACT)


class GenericDatasetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "orders.csv"
        self.input.write_text(HEADER + "\n".join(ROWS) + "\n", encoding="utf-8")

    def build_config(self, **overrides):
        settings = {
            "dataset": "orders", "source_type": "csv", "input_path": str(self.input),
            "curated_dir": str(self.root / "curated"), "quarantine_threshold": 0.9,
            "page_size": 2,
        }
        settings.update(overrides)
        return make_config(**settings)

    def run_factory(self, **overrides):
        return run_pipeline(self.build_config(**overrides), dataset=ORDERS)

    def test_small_config_without_any_nyc_fields(self):
        from nyc311_factory.config import Config
        config = Config(quarantine_threshold=0.9, curated_dir=str(self.root / "small"),
                        source_type="csv", input_path=str(self.input))
        manifest = run_pipeline(config, dataset=ORDERS)
        self.assertEqual(manifest["records"]["passed"], 2)
        self.assertIsNone(manifest["window"])

    def test_contract_is_consistent(self):
        check_contract(ORDERS_CONTRACT)  # must not raise

    def test_validation_and_quarantine_work_for_another_dataset(self):
        manifest = self.run_factory()
        self.assertEqual(manifest["records"]["raw"], 6)
        self.assertEqual(manifest["records"]["passed"], 2)
        self.assertEqual(manifest["records"]["quarantine_by_reason"], {
            "BAD_AMOUNT": 1, "BAD_STATUS": 1, "DUPLICATE_KEY": 1, "SHIPPED_BEFORE_ORDERED": 1,
        })

    def test_clean_values_follow_the_contract(self):
        self.run_factory()
        cases = pd.read_csv(self.root / "curated" / "cases.csv", dtype=str)
        self.assertEqual(list(cases["status"]), ["NEW", "DONE"])  # upper-cased by the contract
        self.assertEqual(list(cases.columns), ORDERS_CONTRACT.output_names)

    def test_manifest_describes_the_file_source(self):
        manifest = self.run_factory()
        self.assertEqual(manifest["source"]["type"], "csv")
        self.assertEqual(len(manifest["source"]["sha256"]), 64)
        self.assertEqual(manifest["joins"], {})

    def test_second_run_gives_same_hashes(self):
        first = self.run_factory()
        second = self.run_factory()
        self.assertEqual(first["output_hashes"], second["output_hashes"])

    def test_threshold_failure_stops_the_run(self):
        with self.assertRaises(QuarantineThresholdError):
            self.run_factory(quarantine_threshold=0.1)
        self.assertFalse((self.root / "curated" / "cases.csv").exists())

    def test_missing_required_column_in_header_is_schema_drift(self):
        self.input.write_text("order_id,status\n1,NEW\n", encoding="utf-8")
        with self.assertRaises(SchemaDriftError):
            self.run_factory()

    def test_missing_input_file_is_config_error(self):
        self.input.unlink()
        with self.assertRaises(ConfigError):
            self.run_factory()


@unittest.skipIf(sqlalchemy is None, "SQLAlchemy is not installed")
class DatabaseDestinationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "orders.csv"
        self.input.write_text(HEADER + "\n".join(ROWS) + "\n", encoding="utf-8")
        self.engine = sqlalchemy.create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

    def count_rows(self, table):
        with self.engine.connect() as connection:
            statement = sqlalchemy.text(f'SELECT COUNT(*) FROM "{table}"')
            return connection.execute(statement).scalar()

    def run_factory(self):
        config = make_config(
            dataset="orders", source_type="csv", input_path=str(self.input),
            curated_dir=str(self.root / "curated"), quarantine_threshold=0.9,
            destinations=("database",))
        return run_pipeline(config, dataset=ORDERS, engine=self.engine)

    def test_clean_and_quarantine_tables_are_loaded(self):
        manifest = self.run_factory()
        self.assertEqual(self.count_rows("orders"), manifest["records"]["passed"])
        self.assertEqual(self.count_rows("orders_quarantine"), manifest["records"]["quarantined_rows"])

    def test_second_run_does_not_duplicate_rows(self):
        self.run_factory()
        self.run_factory()
        self.assertEqual(self.count_rows("orders"), 2)
        self.assertEqual(self.count_rows("orders_quarantine"), 4)

    def test_manifest_lists_database_destinations(self):
        manifest = self.run_factory()
        tables = {item["table"] for item in manifest["destinations"]}
        self.assertEqual(tables, {"orders", "orders_quarantine"})
