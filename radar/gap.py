"""Market-gap engine: is there a strong problem AND no strong solution?

For each theme:
  1. SolutionMapper (Claude + web search) maps every existing solution and rates how well
     each one covers THIS problem for THIS buyer (0-5), plus maturity (1-5). It also rates
     the risk that a platform ships it free within 12 months, and names the uncovered
     whitespace and a wedge product.
  2. ComplaintProbe searches the same people-sources (HN, Reddit, GitHub, ...) for users
     complaining about the top solutions. Dissatisfaction weakens a solution even when its
     marketing claims full coverage.
  3. GapSkeptic tries to REFUTE the gap by finding one solution that already covers it
     at 4/5 or better. If it succeeds, the strongest solution's coverage is raised.
  4. Deterministic, transparent math (below) turns this into a gap score and a quadrant.

  problem_strength  = weighted(pain .30, frequency .25, willingness_to_pay .30, momentum .15), scaled to 0-1
  solution_strength = max over solutions of coverage/5 * (0.6 + 0.4*maturity/5) * (1 - dissatisfaction)
                      dissatisfaction = min(0.4, 0.1 * user-complaint count for that solution)
  gap_score         = 100 * problem_strength * (1 - solution_strength) * (1 - 0.4 * (absorption_risk-1)/4)

  Quadrants (thresholds in config):
    TRUE GAP          strong problem, weak solutions        -> build / invest
    CROWDED           strong problem, strong solutions      -> only with a sharp wedge
    UNDERSERVED NICHE weak problem, weak solutions          -> watch for momentum
    SOLVED            weak problem, strong solutions        -> ignore
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from pydantic import BaseModel, Field

from .models import Post, Scores, Theme

log = logging.getLogger("radar.gap")

# ---------------------------------------------------------------- models


class Solution(BaseModel):
    name: str
    url: str
    kind: str = Field(description="startup | open-source | incumbent-product | platform-native-feature")
    coverage: int = Field(ge=0, le=5, description="How fully it solves THIS exact problem for THIS buyer; 5 = fully, shipped, GA")
    maturity: int = Field(ge=1, le=5, description="1 waitlist/demo, 3 GA with paying customers, 5 category leader")
    adoption_signal: str = Field(description="customers, GitHub stars, funding, ARR; empty if unknown")
    pricing: str
    weaknesses: str = Field(description="What it misses for this specific problem")


class SolutionMap(BaseModel):
    solutions: list[Solution]
    absorption_risk: int = Field(ge=1, le=5, description="Likelihood a platform (OpenAI, Anthropic, Microsoft, Google, AWS, "
                                                         "Okta, GitHub, Salesforce...) ships this free or bundled within 12 months")
    absorption_note: str
    whitespace: str = Field(description="The specific slice of the problem no solution handles; empty if none")
    wedge: str = Field(description="The narrowest product a new entrant could ship to own the whitespace")


class Complaint(BaseModel):
    post_index: int
    solution: str = Field(description="Exact solution name from the list, or empty")
    is_complaint: bool = Field(description="true only if the author is a user complaining about that solution failing them")
    complaint: str


class ComplaintBatch(BaseModel):
    complaints: list[Complaint]


class CounterCheck(BaseModel):
    strongest_solution: str
    url: str
    coverage: int = Field(ge=0, le=5)
    gap_holds: bool = Field(description="true if nothing covers the problem at >=4 for the stated buyer")
    reason: str
    missed_solutions: list[str]


class GapResult(BaseModel):
    solution_map: SolutionMap | None = None
    complaints: dict[str, list[dict]] = {}  # solution name -> [{quote, url, date}]
    counter: CounterCheck | None = None
    problem_strength: float = 0.0
    solution_strength: float = 0.0
    strongest_solution: str = ""
    gap_score: float = 0.0
    quadrant: str = "UNKNOWN"


# ---------------------------------------------------------------- math

PROBLEM_WEIGHTS = {"pain": 0.30, "frequency": 0.25, "willingness_to_pay": 0.30, "momentum": 0.15}


def problem_strength(s: Scores) -> float:
    return round((sum(getattr(s, k) * w for k, w in PROBLEM_WEIGHTS.items()) - 1) / 4, 3)


def solution_strength(sm: SolutionMap, complaints: dict[str, list], counter: CounterCheck | None) -> tuple[float, str]:
    best, name = 0.0, ""
    for s in sm.solutions:
        dissatisfaction = min(0.4, 0.1 * len(complaints.get(s.name, [])))
        v = s.coverage / 5 * (0.6 + 0.4 * s.maturity / 5) * (1 - dissatisfaction)
        if v > best:
            best, name = v, s.name
    if counter and not counter.gap_holds and counter.coverage >= 4:
        # The skeptic found a real covering solution; assume GA maturity unless already mapped stronger.
        v = counter.coverage / 5 * 0.92
        if v > best:
            best, name = v, counter.strongest_solution
    return round(best, 3), name


def gap_score(ps: float, ss: float, absorption_risk: int) -> float:
    return round(100 * ps * (1 - ss) * (1 - 0.4 * (absorption_risk - 1) / 4), 1)


def quadrant(ps: float, ss: float, problem_cut: float = 0.55, solution_cut: float = 0.55) -> str:
    if ps >= problem_cut:
        return "TRUE GAP" if ss < solution_cut else "CROWDED"
    return "UNDERSERVED NICHE" if ss < solution_cut else "SOLVED"


# ---------------------------------------------------------------- agents

MAPPER_SYSTEM = (
    "You are a buy-side analyst mapping the CURRENT solution landscape for one problem. Use web search to find startups, "
    "open-source projects, incumbent products and platform-native features (check product sites, GitHub, Product Hunt, "
    "YC and funding news, G2, changelogs). Be strict about coverage: a roadmap item, a waitlist, or a generic tool that "
    "could be configured to help scores 2 or less. Never invent products or URLs."
)
COMPLAINT_SYSTEM = (
    "Classify posts. A complaint counts only if the author personally used the named solution and it failed them on this "
    "problem (missing capability, unreliable, too expensive, too complex). Marketing, comparisons and questions are not complaints."
)
COUNTER_SYSTEM = (
    "You are an adversarial diligence analyst. Your job is to REFUTE a claimed market gap by finding the single strongest "
    "existing solution that already solves the exact problem for the stated buyer. Default to skepticism, but do not "
    "overstate coverage: name a real, shipped product."
)


class GapEngine:
    def __init__(self, llm, model: str, effort: str, sources: list, searches: int = 6,
                 complaint_solutions: int = 3, problem_cut: float = 0.55, solution_cut: float = 0.55):
        self.llm, self.model, self.effort, self.searches = llm, model, effort, searches
        self.sources = [s for s in sources if s.name != "web"]  # cheap keyword sources only
        self.complaint_solutions = complaint_solutions
        self.problem_cut, self.solution_cut = problem_cut, solution_cut

    def map_solutions(self, theme: Theme, known: list[str]) -> SolutionMap:
        brief = (f"Problem: {theme.title}\n{theme.problem}\nBuyer/sufferer: {theme.who_has_it}\n"
                 f"Already known (verify and extend): {', '.join(known) or 'none'}")
        notes = self.llm.research(model=self.model, effort=self.effort, system=MAPPER_SYSTEM, user=brief,
                                  max_searches=self.searches, max_fetches=self.searches)
        return self.llm.structured(model=self.model, effort=self.effort, system=MAPPER_SYSTEM, schema=SolutionMap,
                                   max_tokens=16000, user=f"{brief}\n\nResearch notes:\n{notes}")

    def probe_complaints(self, theme: Theme, sm: SolutionMap, since: datetime) -> dict[str, list[dict]]:
        top = sorted(sm.solutions, key=lambda s: (s.coverage, s.maturity), reverse=True)[: self.complaint_solutions]
        posts: list[Post] = []
        for s in top:
            for q in (f"{s.name} problems", f"{s.name} alternative"):
                for src in self.sources:
                    posts.extend(src.safe_search(q, since, 10))
        posts = list({p.uid: p for p in posts}.values())[:60]
        if not posts:
            return {}
        body = "\n\n".join(f"[{i}] ({p.source} {p.created_at.date() if p.created_at else ''}) {p.snippet(900)}"
                           for i, p in enumerate(posts))
        out = self.llm.structured(
            model=self.model, effort="low", system=COMPLAINT_SYSTEM, schema=ComplaintBatch, max_tokens=16000,
            user=f"Problem: {theme.title}\nSolutions: {', '.join(s.name for s in top)}\n\nPosts:\n{body}",
        )
        names = {s.name for s in top}
        found: dict[str, list[dict]] = {}
        for c in out.complaints:
            if c.is_complaint and c.solution in names and 0 <= c.post_index < len(posts):
                p = posts[c.post_index]
                found.setdefault(c.solution, []).append(
                    {"quote": c.complaint, "url": p.url, "date": p.created_at.date().isoformat() if p.created_at else ""})
        return found

    def counter(self, theme: Theme, sm: SolutionMap) -> CounterCheck:
        listed = ", ".join(f"{s.name} ({s.coverage}/5)" for s in sm.solutions)
        notes = self.llm.research(
            model=self.model, effort=self.effort, system=COUNTER_SYSTEM, max_searches=3, max_fetches=3,
            user=f"Problem: {theme.title}\n{theme.problem}\nBuyer: {theme.who_has_it}\nClaimed whitespace: {sm.whitespace}\n"
                 f"Solutions already considered: {listed}\nFind what they missed.")
        return self.llm.structured(model=self.model, effort=self.effort, system=COUNTER_SYSTEM, schema=CounterCheck,
                                   max_tokens=8000, user=f"Problem: {theme.title}\nWhitespace: {sm.whitespace}\n"
                                                         f"Considered: {listed}\n\nYour research:\n{notes}")

    def assess(self, theme: Theme, scores: Scores | None, known: list[str], since: datetime) -> GapResult:
        res = GapResult()
        if scores is None:
            return res
        res.problem_strength = problem_strength(scores)
        try:
            res.solution_map = self.map_solutions(theme, known)
        except Exception as e:
            log.warning("solution mapper failed for %s: %s", theme.id, e)
            return res
        with ThreadPoolExecutor(2) as ex:
            fc = ex.submit(self.probe_complaints, theme, res.solution_map, since)
            fk = ex.submit(self.counter, theme, res.solution_map)
            try:
                res.complaints = fc.result()
            except Exception as e:
                log.warning("complaint probe failed for %s: %s", theme.id, e)
            try:
                res.counter = fk.result()
            except Exception as e:
                log.warning("gap skeptic failed for %s: %s", theme.id, e)
        res.solution_strength, res.strongest_solution = solution_strength(res.solution_map, res.complaints, res.counter)
        res.gap_score = gap_score(res.problem_strength, res.solution_strength, res.solution_map.absorption_risk)
        res.quadrant = quadrant(res.problem_strength, res.solution_strength, self.problem_cut, self.solution_cut)
        return res
