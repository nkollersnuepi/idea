"""Shared HTTP helper and source interface. Stdlib-only so sources have no extra deps."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Post

log = logging.getLogger("radar.sources")
USER_AGENT = os.environ.get("RADAR_USER_AGENT", "agentic-radar/0.1 (research crawler)")


def get_json(url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3) -> dict | list:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    h = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = float(e.headers.get("retry-after") or delay)
                log.warning("HTTP %s from %s, retrying in %.0fs", e.code, url.split("?")[0], wait)
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
