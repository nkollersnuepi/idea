"""Stack Exchange network search (questions). STACKEXCHANGE_KEY raises quota."""

from __future__ import annotations

import html
import os
import re
import time
from datetime import datetime, timezone

from ..models import Post
from .base import Source, get_json

_TAG = re.compile(r"<[^>]+>")


class StackExchange(Source):
    name = "stackexchange"

    def __init__(self, sites: list[str]):
        self.sites = sites
        self.exhausted = False

    def search(self, query, since, limit):
        out = []
        for site in self.sites:
            if self.exhausted:
                break
            params = {
                "order": "desc", "sort": "creation", "q": query, "site": site,
                "fromdate": int(since.timestamp()), "pagesize": min(limit, 100), "filter": "withbody",
            }
            if os.environ.get("STACKEXCHANGE_KEY"):
                params["key"] = os.environ["STACKEXCHANGE_KEY"]
            data = get_json("https://api.stackexchange.com/2.3/search/advanced", params)
            if data.get("backoff"):  # mandatory per API terms
                time.sleep(min(int(data["backoff"]), 60))
            if data.get("quota_remaining", 1) <= 0:
                self.exhausted = True
                import logging
                logging.getLogger("radar.sources").warning("stackexchange daily quota exhausted; set STACKEXCHANGE_KEY")
            for it in data.get("items", []):
                out.append(Post(
                    source=self.name, external_id=f"{site}:{it['question_id']}", url=it["link"],
                    author=(it.get("owner") or {}).get("display_name", ""),
                    title=html.unescape(it.get("title", "")),
                    text=html.unescape(_TAG.sub(" ", it.get("body", "")))[:6000],
                    created_at=datetime.fromtimestamp(it["creation_date"], tz=timezone.utc),
                    engagement=int(it.get("score", 0)) + int(it.get("answer_count", 0)) + int(it.get("view_count", 0)) // 100,
                    query=query,
                ))
        return out
