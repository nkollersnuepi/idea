"""Bluesky public post search (AppView, no auth)."""

from __future__ import annotations

from datetime import datetime, timezone

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
            try:
                rec = p.get("record", {})
                handle = p.get("author", {}).get("handle", "")
                rkey = p["uri"].rsplit("/", 1)[-1]
                out.append(Post(
                    source=self.name, external_id=p["uri"],
                    url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                    author=handle, text=rec.get("text", ""),
                    created_at=_ts(rec.get("createdAt")) or _ts(p.get("indexedAt")),
                    engagement=int(p.get("likeCount") or 0) + int(p.get("replyCount") or 0) + int(p.get("repostCount") or 0),
                    query=query,
                ))
            except Exception:  # skip one malformed record, keep the rest
                continue
        return out


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
