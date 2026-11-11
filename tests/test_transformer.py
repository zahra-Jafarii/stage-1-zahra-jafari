import os
import tempfile
import unittest

import pandas as pd

from nyc311_factory.contract import DUPLICATE_CONTENT, DUPLICATE_KEY
from nyc311_factory.datasets.nyc311 import (
    add_derived_columns, build_enrichers, load_population,
)
from nyc311_factory.exceptions import ConfigError, DataValidationError
from nyc311_factory.parsing import clean_zip
from nyc311_factory.transformer import DuplicateTracker, clean_batch, to_frame
from tests.helpers import SOURCE_NAMES, good_record, make_config, make_contract

CONTRACT = make_contract()


def frame_of(*records):
    return to_frame(list(records), SOURCE_NAMES)


def clean_frame(*records):
    return add_derived_columns(clean_batch(frame_of(*records), CONTRACT))


def clean_one(**overrides):
    return clean_frame(good_record(**overrides)).iloc[0]


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


class CleaningPolicyTest(unittest.TestCase):
    def test_missing_descriptor_gets_unknown_label(self):
        self.assertEqual(clean_one(descriptor=None)["descriptor"], "Unknown")
        self.assertEqual(clean_one(descriptor="  ")["descriptor"], "Unknown")

    def test_text_is_stripped_and_borough_upper_cased(self):
        row = clean_one(agency=" NYPD ", borough=" brooklyn ")
        self.assertEqual((row["agency"], row["borough"]), ("NYPD", "BROOKLYN"))

    def test_bad_number_becomes_empty(self):
        self.assertTrue(pd.isna(clean_one(latitude="abc")["latitude"]))


class DuplicateTest(unittest.TestCase):
    def test_same_key_is_technical_duplicate(self):
        kept, duplicates = DuplicateTracker(CONTRACT).split(frame_of(good_record(), good_record()))
        self.assertEqual(len(kept), 1)
        self.assertEqual(list(duplicates["reason_codes"]), [DUPLICATE_KEY])

    def test_same_content_other_key_is_content_duplicate(self):
        frame = frame_of(good_record(), good_record(unique_key="101"))
        kept, duplicates = DuplicateTracker(CONTRACT).split(frame)
        self.assertEqual(len(kept), 1)
        self.assertEqual(list(duplicates["reason_codes"]), [DUPLICATE_CONTENT])

    def test_different_address_is_not_duplicate(self):
        frame = frame_of(good_record(), good_record(unique_key="101", incident_address="2 OAK AVE"))
        kept, duplicates = DuplicateTracker(CONTRACT).split(frame)
        self.assertEqual((len(kept), len(duplicates)), (2, 0))

    def test_duplicates_are_found_across_batches(self):
        tracker = DuplicateTracker(CONTRACT)
        tracker.split(frame_of(good_record()))
        _, duplicates = tracker.split(frame_of(good_record()))
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
        config = self.write_population("zip,borough,population\n10001,MANHATTAN,20000\n")
        frame = clean_frame(good_record(), good_record(unique_key="101", incident_zip="11201"))
        joined = build_enrichers(config)[0].apply(frame)
        self.assertEqual(len(joined), 2)
        self.assertEqual(int(joined["population"].isna().sum()), 1)

    def test_repeated_zip_in_population_is_rejected(self):
        config = self.write_population("zip,borough,population\n10001,MANHATTAN,1\n10001,MANHATTAN,2\n")
        with self.assertRaises(DataValidationError):
            load_population(config)

    def test_missing_population_column_is_config_error(self):
        config = self.write_population("zip,borough,people\n10001,MANHATTAN,1\n")
        with self.assertRaises(ConfigError):
            load_population(config)

    def test_borough_mismatch_is_counted(self):
        config = self.write_population("zip,borough,population\n10001,BROOKLYN,20000\n")
        join = build_enrichers(config)[0]
        join.apply(clean_frame(good_record()))  # case says MANHATTAN, reference says BROOKLYN
        report = join.consistency_report()
        self.assertEqual(report["mismatch_rows"], 1)
        self.assertEqual(report["top_mismatch_pairs"][0]["reference_value"], "BROOKLYN")
