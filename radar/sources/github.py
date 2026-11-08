"""GitHub issues & discussions search. Uses GITHUB_TOKEN (or GH_TOKEN) when set."""

from __future__ import annotations

import os
from datetime import datetime

from ..models import Post
from .base import Source, get_json


class GitHub(Source):
    name = "github"

    def __init__(self, suffix: str = "is:issue created:>{since}"):
        self.suffix = suffix

    def search(self, query, since, limit):
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        q = f"{query} {self.suffix.format(since=since.date().isoformat())}"
        data = get_json("https://api.github.com/search/issues",
                        {"q": q, "sort": "reactions", "order": "desc", "per_page": min(limit, 100)}, headers)
        out = []
        for it in data.get("items", []):
            reactions = (it.get("reactions") or {}).get("total_count", 0)
            out.append(Post(
                source=self.name, external_id=str(it["id"]), url=it["html_url"],
                author=(it.get("user") or {}).get("login", ""), title=it.get("title") or "",
                text=(it.get("body") or "")[:6000],
                created_at=datetime.fromisoformat(it["created_at"].replace("Z", "+00:00")),
                engagement=int(reactions) + int(it.get("comments") or 0),
                query=query,
            ))
        return out
