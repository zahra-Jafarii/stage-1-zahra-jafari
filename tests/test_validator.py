import unittest
from datetime import datetime

from nyc311_factory.exceptions import SchemaDriftError
from nyc311_factory.schema import (
    CLOSED_BEFORE_CREATED, CREATED_OUT_OF_WINDOW, INVALID_ZIP,
    MISSING_AGENCY, MISSING_COMPLAINT_TYPE, REQUIRED_COLUMNS, UNKNOWN_BOROUGH,
)
from nyc311_factory.validator import (
    check_batch_types, check_required_columns, split_valid, validate_record,
)
from tests.helpers import good_record

WINDOW = (datetime(2024, 1, 1), datetime(2024, 3, 1))


def reasons_for(**overrides):
    return validate_record(good_record(**overrides), *WINDOW)


class ValidatorTest(unittest.TestCase):
    def test_good_record_passes(self):
        self.assertEqual(reasons_for(), [])

    def test_closed_before_created_is_flagged(self):
        self.assertEqual(reasons_for(closed_date="2024-01-04T09:00:00.000"),
                         [CLOSED_BEFORE_CREATED])

    def test_open_case_is_valid(self):
        self.assertEqual(reasons_for(closed_date=None), [])

    def test_placeholder_zips_are_flagged(self):
        for bad_zip in ("00000", "N/A", "", None, "1000"):
            self.assertIn(INVALID_ZIP, reasons_for(incident_zip=bad_zip))

    def test_zip_with_spaces_is_accepted(self):
        self.assertEqual(reasons_for(incident_zip=" 10001 "), [])

    def test_window_boundaries(self):
        # start is inclusive, end is exclusive
        self.assertEqual(reasons_for(created_date="2024-01-01T00:00:00.000", closed_date=None), [])
        self.assertEqual(reasons_for(created_date="2024-03-01T00:00:00.000", closed_date=None),
                         [CREATED_OUT_OF_WINDOW])

    def test_unspecified_borough_is_flagged(self):
        self.assertEqual(reasons_for(borough="Unspecified"), [UNKNOWN_BOROUGH])

    def test_all_reasons_are_reported(self):
        reasons = reasons_for(agency="", complaint_type="", incident_zip="N/A")
        self.assertEqual(set(reasons), {MISSING_AGENCY, MISSING_COMPLAINT_TYPE, INVALID_ZIP})

    def test_split_valid_separates_records(self):
        batch = [good_record(), good_record(unique_key="101", borough="Unspecified")]
        valid, rejected = split_valid(batch, *WINDOW)
        self.assertEqual(len(valid), 1)
        self.assertEqual(rejected[0][0]["unique_key"], "101")

    def test_missing_required_column_is_schema_drift(self):
        with self.assertRaises(SchemaDriftError):
            check_required_columns({"unique_key"})
        check_required_columns(set(REQUIRED_COLUMNS))  # must not raise

    def test_changed_column_type_is_schema_drift(self):
        with self.assertRaises(SchemaDriftError):
            check_batch_types([{"unique_key": 5}])