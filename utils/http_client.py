from __future__ import annotations

import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class CircuitBreaker:
    """Small per-source circuit breaker for public API failures.

    It prevents a full run from wasting time on repeated DNS/API failures. Use one breaker per data source.
    """

    def __init__(self, max_failures: int = 2):
        self.max_failures = max(1, int(max_failures))
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        return self.failures >= self.max_failures

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.is_open and self.opened_at is None:
            self.opened_at = time.time()


def build_session(user_agent: str = "CryptoAlphaEngine/0.7.3 SAFE_MODE") -> requests.Session:
    """Create a requests session with conservative retry/backoff for public market APIs."""
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.45,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=24, pool_maxsize=24)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": user_agent})
    return session


def get_json(session: requests.Session, url: str, *, params: dict | None = None, timeout: int | tuple[int, int] = (5, 15)):
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()
