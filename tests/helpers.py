"""Shared fixtures: config, fake HTTP objects, sample records."""
from nyc311_factory.config import Config
from nyc311_factory.datasets.nyc311 import SOURCE_COLUMNS, build_contract

CONFIG_DEFAULTS = {
    "api_url": "https://example.invalid/data.json",
    "start_date": "2024-01-01",
    "end_date": "2024-03-01",
    "key_suffix_digits": ("3",),
    "http_method": "GET",
    "page_size": 2,
    "max_retries": 2,
    "backoff_base_seconds": 1.0,
    "timeout_seconds": 5,
    "quarantine_threshold": 0.05,
    "top_complaint_types": 5,
    "raw_dir": "raw",
    "curated_dir": "curated",
    "population_file": "population.csv",
    "population_zip_column": "zip",
    "population_value_column": "population",
    "app_token_env": "TEST_TOKEN_NOT_SET",
    "track_memory": False,
    "source_type": "api",
    "dataset": "nyc311",
    "population_source_url": "https://example.invalid/population.csv",
    "population_source_retrieved": "2026-01-01",
}


def make_config(**overrides) -> Config:
    return Config(**{**CONFIG_DEFAULTS, **overrides})


def make_contract(**config_overrides):
    return build_contract(make_config(**config_overrides))


SOURCE_NAMES = [column.name for column in SOURCE_COLUMNS]


def good_record(**overrides) -> dict:
    record = {
        "unique_key": "100",
        "created_date": "2024-01-05T10:00:00.000",
        "closed_date": "2024-01-05T12:30:00.000",
        "agency": "NYPD",
        "complaint_type": "Noise - Residential",
        "descriptor": "Loud Music/Party",
        "incident_zip": "10001",
        "incident_address": "1 MAIN ST",
        "borough": "MANHATTAN",
        "community_board": "01 MANHATTAN",
        "status": "Closed",
        "resolution_description": "Done",
        "latitude": "40.75",
        "longitude": "-73.99",
    }
    record.update(overrides)
    return record


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self.payload = payload
        self.bad_json = bad_json

    def json(self):
        if self.bad_json:
            raise ValueError("not json")
        return self.payload


class FakeSession:
    """Returns queued outcomes; an Exception outcome is raised."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers = {}
        self.calls = []

    def _next(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)


class FakeClient:
    """Stands in for HttpClient: returns queued pages, records params."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []
        self.request_count = 0

    def request_json(self, url, params, method=None):
        self.calls.append(params)
        self.request_count += 1
        return self.pages.pop(0)