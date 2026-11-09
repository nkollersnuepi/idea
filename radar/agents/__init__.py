"""The agent roster. Each agent is one well-scoped Claude call with a typed output."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from ..models import (Assessment, ExtractionBatch, Post, Problem, QueryPlan, SkepticVerdict, Theme, ThemeSet)
from . import prompts
from .llm import LLM, AgentError, AgentRefused

log = logging.getLogger("radar.agents")


class Planner:
    """Turns each theme seed into complaint-shaped search queries."""

    def __init__(self, llm: LLM, model: str, effort: str):
        self.llm, self.model, self.effort = llm, model, effort

    def plan(self, theme_name: str, seed: str, n: int = 10) -> list[str]:
        out = self.llm.structured(
            model=self.model, effort=self.effort, system=prompts.PLANNER, schema=QueryPlan, max_tokens=8000,
            user=f"Theme '{theme_name}': {seed}\nWrite {n} distinct queries.",
        )
        return [q.strip() for q in out.queries if q.strip()][:n]


class Extractor:
    """Reads raw posts in batches and pulls out first-person problems."""

    def __init__(self, llm: LLM, model: str, effort: str, segments: list[str], batch_size: int = 15, workers: int = 8):
        self.llm, self.model, self.effort = llm, model, effort
        self.system = prompts.EXTRACTOR.format(segments=", ".join(segments))
        self.batch_size, self.workers = batch_size, workers

    def _batch(self, posts: list[Post]) -> list[Problem] | None:
        """Problems for this batch, or None if the batch failed (posts stay pending for the next run)."""
        body = "\n\n".join(
            f"<post uid=\"{p.uid}\" source=\"{p.source}\" date=\"{p.created_at.date() if p.created_at else ''}\">\n{p.snippet()}\n</post>"
            for p in posts
        )
        try:
            out = self.llm.structured(model=self.model, effort=self.effort, system=self.system,
                                      schema=ExtractionBatch, max_tokens=32000, user=body)
        except Exception as e:
            log.warning("extractor batch of %d failed, will retry next run: %s", len(posts), e)
            return None
        valid = {p.uid for p in posts}
        return [pr for pr in out.problems if pr.is_problem and pr.post_uid in valid and pr.problem]

    def extract(self, posts: list[Post], on_batch=None) -> list[Problem]:
        """Extract in parallel. `on_batch(posts, problems)` is called (in this thread) for each successful batch."""
        batches = [posts[i:i + self.batch_size] for i in range(0, len(posts), self.batch_size)]
        out: list[Problem] = []
        failed = 0
        with ThreadPoolExecutor(self.workers) as ex:
            for batch, probs in zip(batches, ex.map(self._batch, batches)):
                if probs is None:
                    failed += 1
                    continue
                out.extend(probs)
                if on_batch:
                    on_batch(batch, probs)
        if failed:
            log.warning("%d/%d extractor batches failed; their posts remain pending", failed, len(batches))
        return out


class Clusterer:
    """Merges all problems into distinct, specific themes."""

    def __init__(self, llm: LLM, model: str, effort: str):
        self.llm, self.model, self.effort = llm, model, effort

    def cluster(self, problems: list[Problem], target: str = "15-40") -> list[Theme]:
        lines = "\n".join(
            f"[{i}] ({p.segment}; {p.persona}; pain {p.intensity}) {p.problem}" for i, p in enumerate(problems)
        )
        out = self.llm.structured(
            model=self.model, effort=self.effort, system=prompts.CLUSTERER, schema=ThemeSet,
            user=f"Cluster these {len(problems)} problems into {target} themes.\n\n{lines}",
        )
        n = len(problems)
        seen: set[int] = set()
        for t in out.themes:  # enforce one-theme-per-index and valid indexes
            t.problem_indexes = [i for i in dict.fromkeys(t.problem_indexes) if 0 <= i < n and i not in seen]
            seen.update(t.problem_indexes)
        unassigned = n - len(seen)
        if unassigned:
            log.info("clusterer left %d/%d problems unassigned", unassigned, n)
        return [t for t in out.themes if t.problem_indexes]


class Analyst:
    """Researches a theme on the web (competitors, more evidence) and scores it."""

    def __init__(self, llm: LLM, model: str, effort: str, searches: int = 6):
        self.llm, self.model, self.effort, self.searches = llm, model, effort, searches

    def assess(self, theme: Theme, evidence_text: str) -> Assessment:
        notes = self.llm.research(
            model=self.model, effort=self.effort, system=prompts.ANALYST,
            max_searches=self.searches, max_fetches=self.searches,
            user=f"Theme: {theme.title}\nProblem: {theme.problem}\nWho has it: {theme.who_has_it}\n\nEvidence:\n{evidence_text}",
        )
        return self.llm.structured(
            model=self.model, effort=self.effort, system=prompts.ANALYST_SCORE, schema=Assessment, max_tokens=16000,
            user=f"Theme: {theme.title}\nProblem: {theme.problem}\n\nEvidence:\n{evidence_text}\n\nResearch notes:\n{notes}",
        )


class SkepticPanel:
    """N independent skeptics, each with a different lens. Theme survives on majority."""

    def __init__(self, llm: LLM, model: str, effort: str, n: int = 3):
        self.llm, self.model, self.effort = llm, model, effort
        self.lenses = list(prompts.SKEPTIC_LENSES.values())[:max(1, n)]

    def judge(self, theme: Theme, evidence_text: str, assessment: Assessment | None) -> list[SkepticVerdict]:
        brief = (f"Theme: {theme.title}\nProblem: {theme.problem}\n\nEvidence:\n{evidence_text}\n\n"
                 f"Analyst view:\n{assessment.model_dump_json(indent=1) if assessment else 'n/a'}")

        def one(lens: str):
            try:
                return self.llm.structured(model=self.model, effort=self.effort, schema=SkepticVerdict, max_tokens=8000,
                                           system=prompts.SKEPTIC.format(lens=lens), user=brief)
            except Exception as e:
                log.warning("skeptic failed for %s: %s", theme.id, e)
                return None

        with ThreadPoolExecutor(len(self.lenses)) as ex:
            return [v for v in ex.map(one, self.lenses) if v]


__all__ = ["LLM", "AgentRefused", "Planner", "Extractor", "Clusterer", "Analyst", "SkepticPanel"]
