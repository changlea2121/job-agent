import io
import urllib.error

import pytest

from job_agent.sources import http


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, headers=None):
    return urllib.error.HTTPError("u", code, "err", headers or {}, None)


@pytest.fixture
def requests(monkeypatch):
    """Queue of results for urlopen; records the requests made."""
    queue, seen = [], []

    def urlopen(req, timeout):
        seen.append(req)
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)

    monkeypatch.setattr(http.urllib.request, "urlopen", urlopen)
    return queue, seen


def test_retries_transient_errors_with_backoff(requests):
    queue, seen = requests
    queue += [_http_error(503), urllib.error.URLError("reset"), _http_error(429), b'{"ok": 1}']
    waits = []
    assert http.fetch_json("https://x/jobs", data={"a": 1}, sleep=waits.append) == {"ok": 1}
    assert waits == [1.0, 2.0, 4.0]
    req = seen[0]
    assert req.get_header("User-agent") == http.USER_AGENT
    assert req.get_header("Content-type") == "application/json"
    assert req.data == b'{"a": 1}'


def test_gives_up_after_retries(requests):
    queue, _ = requests
    queue += [_http_error(500)] * (http.RETRIES + 1)
    with pytest.raises(urllib.error.HTTPError):
        http.fetch_bytes("https://x", sleep=lambda s: None)


def test_client_errors_are_not_retried(requests):
    queue, seen = requests
    queue += [_http_error(400)]
    with pytest.raises(urllib.error.HTTPError):
        http.fetch_bytes("https://x", sleep=lambda s: None)
    assert len(seen) == 1


def test_retry_after_is_honoured_and_capped(requests):
    queue, _ = requests
    queue += [_http_error(429, {"Retry-After": "7"}), _http_error(429, {"Retry-After": "999"}),
              _http_error(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), b"ok"]
    waits = []
    assert http.fetch_bytes("https://x", sleep=waits.append) == b"ok"
    assert waits == [7.0, http.MAX_RETRY_AFTER, 4.0]
