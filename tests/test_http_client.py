import unittest

import requests

from nyc311_factory.exceptions import InvalidResponseError, NetworkError
from nyc311_factory.http_client import HttpClient
from tests.helpers import FakeResponse, FakeSession, make_config

URL = "https://example.invalid/data.json"


def build_client(outcomes, **config_overrides):
    session = FakeSession(outcomes)
    sleeps = []
    config = make_config(**config_overrides)
    return HttpClient(config, session=session, sleep=sleeps.append), session, sleeps


class HttpClientTest(unittest.TestCase):
    def test_server_error_is_retried_with_growing_backoff(self):
        outcomes = [FakeResponse(500), FakeResponse(500), FakeResponse(200, [{"unique_key": "1"}])]
        client, _, sleeps = build_client(outcomes)
        self.assertEqual(client.request_json(URL, {}), [{"unique_key": "1"}])
        self.assertEqual(client.request_count, 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_client_error_is_not_retried(self):
        client, session, _ = build_client([FakeResponse(404)])
        with self.assertRaises(NetworkError) as context:
            client.request_json(URL, {})
        self.assertIn("404", str(context.exception))
        self.assertEqual(len(session.calls), 1)

    def test_retries_are_capped(self):
        client, session, _ = build_client([FakeResponse(503)] * 3)
        with self.assertRaises(NetworkError):
            client.request_json(URL, {})
        self.assertEqual(len(session.calls), 3)

    def test_invalid_json_raises_specific_error(self):
        client, session, _ = build_client([FakeResponse(200, bad_json=True)] * 3)
        with self.assertRaises(InvalidResponseError):
            client.request_json(URL, {})
        self.assertEqual(len(session.calls), 3)

    def test_connection_error_is_retried(self):
        outcomes = [requests.ConnectionError("down"), FakeResponse(200, [])]
        client, _, _ = build_client(outcomes)
        self.assertEqual(client.request_json(URL, {}), [])
        self.assertEqual(client.request_count, 2)

    def test_post_sends_params_as_json_body(self):
        client, session, _ = build_client([FakeResponse(200, [])], http_method="POST")
        client.request_json(URL, {"$limit": 1})
        method, _, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(kwargs["json"], {"$limit": 1})

    def test_get_sends_params_in_query(self):
        client, session, _ = build_client([FakeResponse(200, [])])
        client.request_json(URL, {"$limit": 1})
        method, _, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(kwargs["params"], {"$limit": 1})