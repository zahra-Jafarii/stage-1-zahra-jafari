import tempfile
import unittest
from pathlib import Path

from nyc311_factory.exceptions import QuarantineThresholdError, SchemaDriftError
from nyc311_factory.pipeline import ProcessStats, check_quarantine_ratio, run_pipeline
from tests.helpers import FakeClient, good_record, make_config


class QuarantineRatioTest(unittest.TestCase):
    def test_ratio_above_threshold_fails(self):
        stats = ProcessStats(raw_count=100, quarantine_rows=10)
        with self.assertRaises(QuarantineThresholdError):
            check_quarantine_ratio(stats, make_config(quarantine_threshold=0.05))

    def test_ratio_below_threshold_passes(self):
        stats = ProcessStats(raw_count=100, quarantine_rows=3)
        check_quarantine_ratio(stats, make_config(quarantine_threshold=0.05))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "population.csv").write_text(
            "zip,borough,population\n10001,MANHATTAN,20000\n11201,MANHATTAN,50000\n",
            encoding="utf-8")
        self.page = [
            good_record(unique_key="1"),
            good_record(unique_key="2", incident_zip="11201", borough="BROOKLYN",
                        incident_address="2 OAK AVE", closed_date=None),
            good_record(unique_key="3", closed_date="2024-01-04T09:00:00.000"),
            good_record(unique_key="1"),
        ]

    def build_config(self, **overrides):
        settings = {
            "start_date": "2024-01-01", "end_date": "2024-02-01",
            "key_suffix_digits": (), "page_size": 100, "quarantine_threshold": 0.6,
            "raw_dir": str(self.root / "raw"), "curated_dir": str(self.root / "curated"),
            "population_file": str(self.root / "population.csv"),
        }
        settings.update(overrides)
        return make_config(**settings)

    def test_counts_by_reason(self):
        manifest = run_pipeline(self.build_config(), client=FakeClient([self.page]))
        self.assertEqual(manifest["records"]["raw"], 4)
        self.assertEqual(manifest["records"]["passed"], 2)
        self.assertEqual(manifest["records"]["quarantine_by_reason"],
                         {"CLOSED_BEFORE_CREATED": 1, "DUPLICATE_KEY": 1})
        self.assertEqual(manifest["joins"]["population"],
                         {"rows_before": 2, "rows_after": 2})

    def test_borough_mismatch_is_reported_in_manifest(self):
        # zip 11201 is MANHATTAN in the reference but BROOKLYN in the case
        manifest = run_pipeline(self.build_config(), client=FakeClient([self.page]))
        check = manifest["reference_checks"]["population"]
        self.assertEqual((check["rows_comparable"], check["mismatch_rows"]), (2, 1))

    def test_manifest_records_reference_source(self):
        manifest = run_pipeline(self.build_config(), client=FakeClient([self.page]))
        source = manifest["reference_sources"]["population"]
        self.assertEqual(source["retrieved"], "2026-01-01")
        self.assertTrue(source["url"].startswith("https://"))

    def test_second_run_gives_same_hashes_without_new_requests(self):
        config, client = self.build_config(), FakeClient([self.page])
        first = run_pipeline(config, client=client)
        second = run_pipeline(config, client=client)
        self.assertEqual(first["output_hashes"], second["output_hashes"])
        self.assertEqual(client.request_count, 1)

    def test_threshold_failure_publishes_no_curated_cases(self):
        config = self.build_config(quarantine_threshold=0.1)
        with self.assertRaises(QuarantineThresholdError):
            run_pipeline(config, client=FakeClient([self.page]))
        self.assertFalse((self.root / "curated" / "cases.csv").exists())
        self.assertTrue((self.root / "curated" / "quarantine.csv").exists())

    def test_dropped_column_stops_the_run(self):
        record = {k: v for k, v in good_record().items() if k != "agency"}
        with self.assertRaises(SchemaDriftError):
            run_pipeline(self.build_config(), client=FakeClient([[record]]))
