"""Data models shared across sources, agents, store and reports."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Post(BaseModel):
    """A raw piece of text written by a person, from any channel."""

    source: str  # hackernews | reddit | github | stackexchange | bluesky | web
    external_id: str
    url: str
    author: str = ""
    title: str = ""
    text: str
    created_at: datetime | None = None
    engagement: int = 0  # points / upvotes / reactions / comments, source-specific
    query: str = ""  # the query that surfaced it

    @property
    def uid(self) -> str:
        return hashlib.sha1(f"{self.source}:{self.external_id}".encode()).hexdigest()[:16]

    def snippet(self, n: int = 1800) -> str:
        body = f"{self.title}\n{self.text}".strip()
        return body if len(body) <= n else body[:n] + " …"


# ---------- Agent outputs (also used as structured-output schemas) ----------


class QueryPlan(BaseModel):
    """Planner output: complaint-shaped search queries per theme."""

    queries: list[str] = Field(description="Short keyword queries (2-6 words) that surface people complaining")


class Problem(BaseModel):
    """A single concrete problem a person states in a post."""

    post_uid: str = Field(description="uid of the post this came from, copied exactly")
    is_problem: bool = Field(description="false if the post contains no first-person problem related to AI agents")
    problem: str = Field(description="One sentence, specific and concrete. Empty if is_problem is false")
    quote: str = Field(description="Verbatim excerpt from the post that states the problem")
    persona: str = Field(description="Who has the problem, e.g. 'platform engineer at a 200-person SaaS'")
    segment: str = Field(description="One of the configured segments, or 'other'")
    intensity: int = Field(ge=0, le=5, description="0-5 pain from the language used")
    wtp_signal: str = Field(description="Evidence they'd pay / already pay / have budget; empty if none")
    workaround: str = Field(description="What they do today; empty if not stated")
    first_person: bool = Field(description="true if the author personally experiences the problem")


class ExtractionBatch(BaseModel):
    problems: list[Problem]


class Theme(BaseModel):
    id: str = Field(description="short kebab-case id")
    title: str = Field(description="specific, e.g. 'No way to replay and diff a failed long agent run'")
    problem: str
    who_has_it: str
    problem_indexes: list[int] = Field(description="indexes of the problems assigned to this theme")


class ThemeSet(BaseModel):
    themes: list[Theme]


class ExistingSolution(BaseModel):
    name: str
    what: str
    gap: str


class Scores(BaseModel):
    pain: int = Field(ge=1, le=5)
    frequency: int = Field(ge=1, le=5)
    willingness_to_pay: int = Field(ge=1, le=5)
    momentum: int = Field(ge=1, le=5)
    solution_gap: int = Field(ge=1, le=5, description="5 = nobody solves it well")
    market_size: int = Field(ge=1, le=5)


class Assessment(BaseModel):
    existing_solutions: list[ExistingSolution]
    scores: Scores
    why_now: str
    who_pays: str
    opportunity: str = Field(description="The product or company that would solve this, 1-2 sentences")
    investable_angle: str = Field(description="Public/private companies exposed as beneficiaries or losers")


class SkepticVerdict(BaseModel):
    survives: bool = Field(description="false if this is vendor hype, already well solved, too niche, or evidence is weak")
    strongest_objection: str
    confidence: int = Field(ge=1, le=5)


class ThemeReport(BaseModel):
    theme: Theme
    evidence: list[dict]
    assessment: Assessment | None = None
    verdicts: list[SkepticVerdict] = []
    opportunity_score: float = 0.0
    survives: bool = True


SCORE_WEIGHTS = {
    "pain": 0.22,
    "frequency": 0.18,
    "willingness_to_pay": 0.22,
    "momentum": 0.13,
    "solution_gap": 0.15,
    "market_size": 0.10,
}


def opportunity_score(s: Scores, evidence_count: int) -> float:
    """Weighted 0-100 score with a small bonus for corroboration breadth."""
    base = sum(getattr(s, k) * w for k, w in SCORE_WEIGHTS.items())  # 1..5
    norm = (base - 1) / 4 * 90  # 0..90
    breadth = min(evidence_count, 10)  # up to +10
    return round(norm + breadth, 1)
