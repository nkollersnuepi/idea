"""Bluesky public post search (AppView, no auth)."""

from __future__ import annotations

from datetime import datetime

from ..models import Post
from .base import Source, get_json


class Bluesky(Source):
    name = "bluesky"

    def search(self, query, since, limit):
        data = get_json("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts", {
            "q": query, "sort": "latest", "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": min(limit, 100),
        })
        out = []
        for p in data.get("posts", []):
            rec = p.get("record", {})
            handle = p.get("author", {}).get("handle", "")
            rkey = p["uri"].rsplit("/", 1)[-1]
            out.append(Post(
                source=self.name, external_id=p["uri"],
                url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                author=handle, text=rec.get("text", ""),
                created_at=datetime.fromisoformat(rec.get("createdAt", p.get("indexedAt")).replace("Z", "+00:00")),
                engagement=int(p.get("likeCount", 0)) + int(p.get("replyCount", 0)) + int(p.get("repostCount", 0)),
                query=query,
            ))
        return out
