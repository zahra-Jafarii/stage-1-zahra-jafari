import os
import tempfile
import unittest
from datetime import date

from nyc311_factory.exceptions import InvalidResponseError
from nyc311_factory.fetcher import (
    Checkpoint, Partition, build_params, check_page, fetch_all,
    fetch_partition, partition_path, plan_partitions,
)
from tests.helpers import SOURCE_NAMES, FakeClient, make_config


class FetcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw_dir = os.path.join(self.tmp.name, "raw")
        os.makedirs(self.raw_dir)
        self.config = make_config(raw_dir=self.raw_dir)

    def test_partitions_follow_month_boundaries(self):
        parts = plan_partitions(date(2024, 1, 15), date(2024, 3, 10))
        self.assertEqual([p.name for p in parts], ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(parts[0].start, date(2024, 1, 15))
        self.assertEqual(parts[-1].end, date(2024, 3, 10))

    def test_params_contain_sampling_and_keyset(self):
        partition = Partition("2024-01", date(2024, 1, 1), date(2024, 2, 1))
        params = build_params(self.config, partition, "abc", SOURCE_NAMES)
        self.assertIn("unique_key like '%3'", params["$where"])
        self.assertIn("unique_key > 'abc'", params["$where"])
        self.assertEqual(params["$order"], "unique_key")

    def test_fetch_partition_follows_keyset_pages(self):
        partition = Partition("2024-01", date(2024, 1, 1), date(2024, 2, 1))
        client = FakeClient([[{"unique_key": "1"}, {"unique_key": "2"}], [{"unique_key": "3"}]])
        rows, _ = fetch_partition(client, self.config, partition, SOURCE_NAMES)
        self.assertEqual(rows, 3)
        self.assertIn("unique_key > '2'", client.calls[1]["$where"])
        with open(partition_path(self.raw_dir, partition), encoding="utf-8") as handle:
            self.assertEqual(len(handle.readlines()), 3)

    def test_bad_pages_are_rejected(self):
        with self.assertRaises(InvalidResponseError):
            check_page({"error": "x"}, None)
        with self.assertRaises(InvalidResponseError):
            check_page([{"no_key": 1}], None)
        with self.assertRaises(InvalidResponseError):
            check_page([{"unique_key": "1"}], "5")  # keyset did not advance

    def test_resume_fetches_only_missing_partitions(self):
        partitions = plan_partitions(date(2024, 1, 1), date(2024, 3, 1))
        page = [{"unique_key": "1"}]
        client = FakeClient([page, page, page])

        summary = fetch_all(client, self.config, partitions, Checkpoint(self.config, SOURCE_NAMES), SOURCE_NAMES)
        self.assertEqual(summary, {"fetched": 2, "reused": 0})

        os.remove(partition_path(self.raw_dir, partitions[1]))  # simulate interruption
        summary = fetch_all(client, self.config, partitions, Checkpoint(self.config, SOURCE_NAMES), SOURCE_NAMES)
        self.assertEqual(summary, {"fetched": 1, "reused": 1})
        self.assertEqual(client.request_count, 3)

    def test_changed_file_invalidates_checkpoint(self):
        partition = Partition("2024-01", date(2024, 1, 1), date(2024, 2, 1))
        fetch_all(FakeClient([[{"unique_key": "1"}]]), self.config, [partition],
                  Checkpoint(self.config, SOURCE_NAMES), SOURCE_NAMES)
        self.assertTrue(Checkpoint(self.config, SOURCE_NAMES).is_complete(partition))
        with open(partition_path(self.raw_dir, partition), "a", encoding="utf-8") as handle:
            handle.write("garbage\n")
        self.assertFalse(Checkpoint(self.config, SOURCE_NAMES).is_complete(partition))

    def test_changed_filter_invalidates_checkpoint(self):
        partition = Partition("2024-01", date(2024, 1, 1), date(2024, 2, 1))
        fetch_all(FakeClient([[{"unique_key": "1"}]]), self.config, [partition],
                  Checkpoint(self.config, SOURCE_NAMES), SOURCE_NAMES)
        other = make_config(raw_dir=self.raw_dir, key_suffix_digits=("4",))
        self.assertFalse(Checkpoint(other, SOURCE_NAMES).is_complete(partition))