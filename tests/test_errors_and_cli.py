import contextlib
import io
import unittest

from nyc311_factory.cli import main
from nyc311_factory.config import load_config, validate_config
from nyc311_factory.exceptions import (
    ConfigError, DataValidationError, InvalidResponseError, NetworkError,
    QuarantineThresholdError, SchemaDriftError,
)
from tests.helpers import make_config


class ExitCodeTest(unittest.TestCase):
    def test_error_families_have_distinct_exit_codes(self):
        classes = [ConfigError, NetworkError, DataValidationError,
                   SchemaDriftError, QuarantineThresholdError]
        self.assertEqual(len({cls.exit_code for cls in classes}), 5)
        self.assertEqual(InvalidResponseError.exit_code, NetworkError.exit_code)

    def test_cli_returns_config_exit_code(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = main(["run", "--config", "missing_config.json"])
        self.assertEqual(code, ConfigError.exit_code)


class ConfigTest(unittest.TestCase):
    def test_start_after_end_is_rejected(self):
        with self.assertRaises(ConfigError):
            validate_config(make_config(start_date="2024-02-01", end_date="2024-01-01"))

    def test_bad_method_and_threshold_are_rejected(self):
        with self.assertRaises(ConfigError):
            validate_config(make_config(http_method="PUT"))
        with self.assertRaises(ConfigError):
            validate_config(make_config(quarantine_threshold=1.5))

    def test_missing_file_is_config_error(self):
        with self.assertRaises(ConfigError):
            load_config("does_not_exist.json")