"""Reddit via public JSON search, scoped to configured subreddits.

Optional OAuth: set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET for higher rate limits.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..models import Post
from .base import USER_AGENT, Source, get_json


class Reddit(Source):
    name = "reddit"

    def __init__(self, subreddits: list[str]):
        self.subreddits = subreddits
        self._token: str | None = None

    def _auth(self) -> dict:
        cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
        if not (cid and secret):
            return {}
        if not self._token:
            req = urllib.request.Request(
                "https://www.reddit.com/api/v1/access_token",
                data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
                headers={"User-Agent": USER_AGENT,
                         "Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                self._token = json.loads(r.read())["access_token"]
        return {"Authorization": f"Bearer {self._token}"}

    def search(self, query, since, limit):
        headers = self._auth()
        base = "https://oauth.reddit.com" if headers else "https://www.reddit.com"
        # Search across all configured subreddits in one multireddit query.
        multi = "+".join(self.subreddits)
        data = get_json(f"{base}/r/{multi}/search.json", {
            "q": query, "restrict_sr": "1", "sort": "new", "t": "year", "limit": min(limit, 100),
        }, headers)
        out = []
        for child in data.get("data", {}).get("children", []):
            d = child["data"]
            created = datetime.fromtimestamp(d["created_utc"], tz=timezone.utc)
            if created < since:
                continue
            out.append(Post(
                source=self.name, external_id=d["id"],
                url="https://www.reddit.com" + d["permalink"],
                author=d.get("author") or "", title=d.get("title") or "",
                text=(d.get("selftext") or "")[:6000],
                created_at=created,
                engagement=int(d.get("score") or 0) + int(d.get("num_comments") or 0),
                query=query,
            ))
        time.sleep(1.0)  # be polite to the unauthenticated endpoint
        return out
