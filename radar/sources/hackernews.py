"""Hacker News via the Algolia search API (stories + comments, no key)."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from ..models import Post
from .base import Source, get_json

API = "https://hn.algolia.com/api/v1/search_by_date"
_TAG = re.compile(r"<[^>]+>")


def clean(s: str | None) -> str:
    return html.unescape(_TAG.sub(" ", s or "")).strip()


class HackerNews(Source):
    name = "hackernews"

    def search(self, query, since, limit):
        data = get_json(API, {
            "query": query,
            "tags": "(story,comment)",
            "numericFilters": f"created_at_i>{int(since.timestamp())}",
            "hitsPerPage": min(limit, 100),
        })
        out = []
        for h in data.get("hits", []):
            text = clean(h.get("comment_text") or h.get("story_text"))
            title = clean(h.get("title") or h.get("story_title"))
            if len(text) < 40 and not title:
                continue
            oid = h["objectID"]
            out.append(Post(
                source=self.name, external_id=oid,
                url=f"https://news.ycombinator.com/item?id={oid}",
                author=h.get("author") or "", title=title, text=text,
                created_at=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
                engagement=int(h.get("points") or 0) + int(h.get("num_comments") or 0),
                query=query,
            ))
        return out
