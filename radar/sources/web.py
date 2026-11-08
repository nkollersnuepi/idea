"""Open-web source: a Claude research agent with web_search/web_fetch.

Covers channels without a usable public API (X/Twitter, LinkedIn, Discourse forums,
vendor community forums, Substack, dev.to, Discord archives) and returns only
first-person posts with URLs.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ..models import Post
from .base import Source

SYSTEM = (
    "You find real people describing their own problems online. You never invent posts, quotes or URLs. "
    "Vendor marketing, analyst reports and news articles are not posts; skip them unless they quote a named user."
)


class WebMention(BaseModel):
    url: str
    platform: str = Field(description="x, linkedin, forum, substack, devto, discord, youtube, other")
    author: str
    date: str = Field(description="YYYY-MM-DD if known, else empty")
    text: str = Field(description="The person's words, as verbatim as possible")


class WebMentions(BaseModel):
    mentions: list[WebMention]


class WebAgent(Source):
    name = "web"

    def __init__(self, llm, model: str, effort: str = "medium", searches: int = 4):
        self.llm, self.model, self.effort, self.searches = llm, model, effort, searches

    def search(self, query, since, limit):
        notes = self.llm.research(
            model=self.model, effort=self.effort, system=SYSTEM, max_searches=self.searches, max_fetches=self.searches,
            user=(
                f"Find up to {limit} posts written since {since.date()} where a person describes this problem first-hand: "
                f"\"{query}\". Prioritise X/Twitter, LinkedIn, community forums (Cursor, LangChain, n8n, OpenAI, Anthropic, "
                f"Discourse), Substack and dev.to. For each, give URL, platform, author, date and their words."
            ),
        )
        found = self.llm.structured(
            model=self.model, effort="low", schema=WebMentions, max_tokens=16000,
            system="Convert research notes into structured records. Keep only entries that have a real URL from the notes.",
            user=notes,
        )
        out = []
        for m in found.mentions[:limit]:
            try:
                created = datetime.fromisoformat(m.date).replace(tzinfo=timezone.utc) if m.date else None
            except ValueError:
                created = None
            if created and created < since:
                continue
            out.append(Post(
                source=f"web:{m.platform}", external_id=hashlib.sha1(m.url.encode()).hexdigest()[:20],
                url=m.url, author=m.author, text=m.text, created_at=created, query=query,
            ))
        return out
