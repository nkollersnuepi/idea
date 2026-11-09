"""Shared HTTP helper and source interface. Stdlib-only so sources have no extra deps."""

from __future__ import annotations

import email.utils
import gzip
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Post

log = logging.getLogger("radar.sources")
USER_AGENT = os.environ.get("RADAR_USER_AGENT", "agentic-radar/0.1 (research crawler)")
MAX_WAIT = 90.0

# Minimum seconds between requests per host (GitHub search: 30/min authenticated, 10/min anonymous).
MIN_INTERVAL = {
    "api.github.com": 2.1 if (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")) else 6.1,
    "www.reddit.com": 2.0,
    "oauth.reddit.com": 0.7,
    "api.stackexchange.com": 0.2,
    "hn.algolia.com": 0.1,
    "public.api.bsky.app": 0.2,
}
_last: dict[str, float] = {}
_pace_lock = threading.Lock()


def _pace(host: str) -> None:
    gap = MIN_INTERVAL.get(host, 0.0)
    with _pace_lock:
        wait = _last.get(host, 0.0) + gap - time.monotonic()
        _last[host] = time.monotonic() + max(wait, 0.0)
    if wait > 0:
        time.sleep(wait)


def _decode(body: bytes, encoding: str | None) -> dict | list:
    enc = (encoding or "").lower()
    if enc == "gzip" or body[:2] == b"\x1f\x8b":  # Stack Exchange always gzips
        body = gzip.decompress(body)
    elif enc == "deflate":
        body = zlib.decompress(body)
    return json.loads(body.decode("utf-8"))


def _retry_wait(e: urllib.error.HTTPError, default: float) -> float | None:
    """Seconds to wait before retrying, or None if the error is not retryable."""
    h = e.headers
    ra = h.get("retry-after") if h else None
    if ra:
        try:
            return min(float(ra), MAX_WAIT)
        except ValueError:
            dt = email.utils.parsedate_to_datetime(ra)
            return min(max(dt.timestamp() - time.time(), 1.0), MAX_WAIT)
    if e.code == 403 and h and h.get("x-ratelimit-remaining") == "0":  # GitHub primary rate limit
        reset = float(h.get("x-ratelimit-reset") or 0)
        return min(max(reset - time.time(), 1.0), MAX_WAIT)
    if e.code in (429, 500, 502, 503, 504):
        return default
    return None


def get_json(url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3) -> dict | list:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    host = urllib.parse.urlsplit(url).netloc
    h = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip", **(headers or {})}
    delay = 2.0
    for attempt in range(retries + 1):
        _pace(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                return _decode(r.read(), r.headers.get("Content-Encoding"))
        except urllib.error.HTTPError as e:
            wait = _retry_wait(e, delay)
            if wait is not None and attempt < retries:
                log.warning("HTTP %s from %s, retrying in %.0fs", e.code, host, wait)
                time.sleep(wait)
                delay *= 2
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


class Source(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, since: datetime, limit: int) -> list[Post]:
        """Return posts matching query created after `since`."""

    def safe_search(self, query: str, since: datetime, limit: int) -> list[Post]:
        try:
            return self.search(query, since, limit)
        except Exception as e:  # one failing source must never kill the run
            log.warning("source %s failed for %r: %s", self.name, query, e)
            return []
