"""HTTP layer: GET/POST, retry with backoff, request counter."""
import os
import time

import requests

from .config import Config
from .exceptions import InvalidResponseError, NetworkError

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class _TransientStatus(Exception):
    """Retryable HTTP status."""


class HttpClient:
    def __init__(self, config: Config, session=None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep
        self.method = config.http_method.upper()
        self.timeout = config.timeout_seconds
        self.max_retries = config.max_retries
        self.backoff_base = config.backoff_base_seconds
        self.request_count = 0
        token = os.environ.get(config.app_token_env)
        if token:
            self.session.headers["X-App-Token"] = token

    def request_json(self, url: str, params: dict, method: str = None):
        method = (method or self.method).upper()
        failure = None
        for attempt in range(self.max_retries + 1):
            self.request_count += 1
            try:
                return self._attempt(method, url, params)
            except (requests.ConnectionError, requests.Timeout) as error:
                failure = NetworkError(f"connection problem: {error}")
            except _TransientStatus as error:
                failure = NetworkError(str(error))
            except InvalidResponseError as error:
                failure = error
            if attempt < self.max_retries:
                self.sleep(self.backoff_base * 2 ** attempt)
        raise failure

    def _attempt(self, method: str, url: str, params: dict):
        if method == "GET":
            response = self.session.get(url, params=params, timeout=self.timeout)
        elif method == "POST":
            response = self.session.post(url, json=params, timeout=self.timeout)
        else:
            raise NetworkError(f"unsupported method {method}")
        status = response.status_code
        if status in RETRYABLE_STATUS:
            raise _TransientStatus(f"HTTP {status}")
        if status != 200:
            raise NetworkError(f"HTTP {status} (not retried)")
        try:
            return response.json()
        except ValueError as error:
            raise InvalidResponseError(f"body is not valid JSON: {error}") from error