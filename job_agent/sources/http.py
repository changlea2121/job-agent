"""HTTP for adapters of unofficial endpoints: a descriptive User-Agent and
retries with exponential backoff on transient errors."""
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

USER_AGENT = (
    "job-agent/0.1 (personal job search, polite polling; "
    "+https://github.com/changlea2121/job-agent)"
)
RETRIES = 3  # after the first attempt
BACKOFF = 1.0  # seconds before the first retry; doubles each time
MAX_RETRY_AFTER = 60.0  # cap on a server's Retry-After, in seconds


def _transient(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _delay(exc: Exception, attempt: int) -> float:
    """The server's Retry-After (in seconds) on a 429 or 503, else backoff."""
    backoff = BACKOFF * 2 ** attempt
    if isinstance(exc, urllib.error.HTTPError) and exc.headers is not None:
        try:
            return min(max(float(exc.headers.get("Retry-After", "")), backoff),
                       MAX_RETRY_AFTER)
        except ValueError:  # absent, or an HTTP date
            pass
    return backoff


def fetch_bytes(
    url: str,
    *,
    data: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """GET `url`, or POST `data` as JSON when given. Retries 429, 5xx and
    network errors up to RETRIES times, waiting BACKOFF, 2x, 4x... seconds,
    or longer when the server sends Retry-After."""
    body = None if data is None else json.dumps(data).encode()
    all_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    if body is not None:
        all_headers["Content-Type"] = "application/json"
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(url, data=body, headers=all_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            if attempt == RETRIES or not _transient(exc):
                raise
            sleep(_delay(exc, attempt))
    raise AssertionError("unreachable")


def fetch_json(url: str, **kwargs) -> Any:
    return json.loads(fetch_bytes(url, headers={"Accept": "application/json",
                                                **kwargs.pop("headers", {})}, **kwargs))
