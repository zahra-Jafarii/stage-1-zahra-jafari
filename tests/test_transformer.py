import os
import tempfile
import unittest

import pandas as pd

from nyc311_factory.exceptions import ConfigError, DataValidationError
from nyc311_factory.parsing import clean_zip
from nyc311_factory.schema import DUPLICATE_CONTENT, DUPLICATE_KEY
from nyc311_factory.transformer import (
    DuplicateTracker, attach_population, clean_batch, load_population, to_frame,
)
from tests.helpers import good_record, make_config


def clean_one(**overrides):
    return clean_batch(to_frame([good_record(**overrides)])).iloc[0]


class DerivedColumnsTest(unittest.TestCase):
    def test_closing_hours(self):
        self.assertAlmostEqual(clean_one()["closing_hours"], 2.5)

    def test_zero_duration_is_valid(self):
        row = clean_one(closed_date="2024-01-05T10:00:00.000")
        self.assertEqual(row["closing_hours"], 0.0)
        self.assertTrue(row["is_closed"])

    def test_open_case_has_no_duration(self):
        row = clean_one(closed_date=None)
        self.assertTrue(pd.isna(row["closing_hours"]))
        self.assertFalse(row["is_closed"])

    def test_month_boundary(self):
        self.assertEqual(clean_one(created_date="2024-01-31T23:59:59.000",
                                   closed_date=None)["year_month"], "2024-01")
        self.assertEqual(clean_one(created_date="2024-02-01T00:00:00.000",
                                   closed_date=None)["year_month"], "2024-02")

    def test_zip_cleaning(self):
        self.assertEqual(clean_zip(" 10001 "), "10001")
        self.assertEqual(clean_zip("10001-1234"), "10001")
        self.assertIsNone(clean_zip("N/A"))
        self.assertIsNone(clean_zip("00000"))


class DuplicateTest(unittest.TestCase):
    def test_same_key_is_technical_duplicate(self):
        kept, duplicates = DuplicateTracker().split(to_frame([good_record(), good_record()]))
        self.assertEqual(len(kept), 1)
        self.assertEqual(list(duplicates["reason_codes"]), [DUPLICATE_KEY])

    def test_same_content_other_key_is_content_duplicate(self):
        frame = to_frame([good_record(), good_record(unique_key="101")])
        kept, duplicates = DuplicateTracker().split(frame)
        self.assertEqual(len(kept), 1)
        self.assertEqual(list(duplicates["reason_codes"]), [DUPLICATE_CONTENT])

    def test_different_address_is_not_duplicate(self):
        frame = to_frame([good_record(), good_record(unique_key="101", incident_address="2 OAK AVE")])
        kept, duplicates = DuplicateTracker().split(frame)
        self.assertEqual((len(kept), len(duplicates)), (2, 0))

    def test_duplicates_are_found_across_batches(self):
        tracker = DuplicateTracker()
        tracker.split(to_frame([good_record()]))
        _, duplicates = tracker.split(to_frame([good_record()]))
        self.assertEqual(len(duplicates), 1)


class PopulationJoinTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write_population(self, text):
        path = os.path.join(self.tmp.name, "population.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return make_config(population_file=path)

    def test_join_keeps_row_count_and_leaves_gaps_empty(self):
        config = self.write_population("zip,population\n10001,20000\n")
        frame = clean_batch(to_frame([good_record(), good_record(unique_key="101", incident_zip="11201")]))
        joined = attach_population(frame, load_population(config))
        self.assertEqual(len(joined), 2)
        self.assertEqual(int(joined["population"].isna().sum()), 1)

    def test_repeated_zip_in_population_is_rejected(self):
        config = self.write_population("zip,population\n10001,1\n10001,2\n")
        with self.assertRaises(DataValidationError):
            load_population(config)

    def test_missing_population_column_is_config_error(self):
        config = self.write_population("zip,people\n10001,1\n")
        with self.assertRaises(ConfigError):
            load_population(config)