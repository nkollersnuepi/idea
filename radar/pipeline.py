"""Orchestrates the agents: plan → collect → extract → cluster → assess → skeptic panel → score."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .agents import LLM, Analyst, Clusterer, Extractor, Planner, SkepticPanel
from .config import Config
from .gap import GapEngine
from .models import Problem, ThemeReport, opportunity_score
from .sources import Source
from .store import Store

log = logging.getLogger("radar.pipeline")


class Pipeline:
    def __init__(self, cfg: Config, llm: LLM, sources: list[Source], store: Store):
        self.cfg, self.llm, self.sources, self.store = cfg, llm, sources, store
        segs = [t.name for t in cfg.themes] or ["general"]
        self.planner = Planner(llm, cfg.model_default, cfg.planner_effort)
        self.extractor = Extractor(llm, cfg.model_extractor, cfg.extractor_effort, segs)
        self.clusterer = Clusterer(llm, cfg.model_default, cfg.clusterer_effort)
        self.analyst = Analyst(llm, cfg.model_default, cfg.analyst_effort)
        self.skeptics = SkepticPanel(llm, cfg.model_default, cfg.skeptic_effort, cfg.skeptics_per_theme)
        self.gap = GapEngine(llm, cfg.model_default, cfg.analyst_effort, sources, cfg.gap_searches,
                             cfg.gap_complaint_solutions, cfg.gap_problem_cut, cfg.gap_solution_cut) if cfg.gap_enabled else None
        self.stats: dict = {}

    # ---------------- stages ----------------
    def plan(self) -> dict[str, list[str]]:
        def one(t):
            try:
                return t.name, self.planner.plan(t.name, t.seed)
            except Exception as e:
                log.warning("planner failed for %s: %s", t.name, e)
                return t.name, [t.seed[:60]]
        with ThreadPoolExecutor(8) as ex:
            plan = dict(ex.map(one, self.cfg.themes))
        self.stats["queries"] = sum(len(v) for v in plan.values())
        return plan

    def collect(self, plan: dict[str, list[str]], run_id: str, now: datetime) -> int:
        since = now - timedelta(days=self.cfg.lookback_days)
        seeds = {t.name: t.seed for t in self.cfg.themes}

        def run_source(src: Source):
            posts = []
            for theme, queries in plan.items():
                # The web agent is expensive: one research task per theme, keyword sources get every query.
                qs = [seeds.get(theme, queries[0])] if src.name == "web" else queries
                for q in qs:
                    posts.extend(src.safe_search(q, since, self.cfg.max_posts_per_query))
            return src.name, posts

        per_source = {}
        total_new = 0
        with ThreadPoolExecutor(len(self.sources) or 1) as ex:
            for name, posts in ex.map(run_source, self.sources):
                fresh = self.store.add_posts(posts, run_id)
                per_source[name] = {"fetched": len(posts), "new": len(fresh)}
                total_new += len(fresh)
        self.stats["sources"] = per_source
        log.info("collected: %s", per_source)
        return total_new

    def extract(self, run_id: str) -> list[Problem]:
        since = datetime.now(timezone.utc) - timedelta(days=self.cfg.lookback_days)
        pending = self.store.count_unextracted()
        posts = self.store.unextracted_posts(self.cfg.max_posts_total, since)
        if pending > len(posts):
            log.warning("cap: extracting %d of %d pending posts (max_posts_total); rest wait for next run",
                        len(posts), pending)
        done = {"posts": 0}

        def persist(batch, probs):  # persist per batch so a crash later loses nothing already paid for
            self.store.add_problems(probs, run_id)
            self.store.mark_extracted([p.uid for p in batch], run_id)
            done["posts"] += len(batch)

        problems = self.extractor.extract(posts, on_batch=persist)
        self.stats["posts_extracted"] = done["posts"]
        self.stats["problems_new"] = len(problems)
        return problems

    def corpus(self, now: datetime) -> list[tuple[Problem, dict]]:
        """All stored problems within the lookback window, with post metadata."""
        since = now - timedelta(days=self.cfg.lookback_days)
        out = []
        for _, pr in self.store.problems():
            if pr.intensity < self.cfg.min_intensity:
                continue
            post = self.store.post(pr.post_uid)
            if not post:
                continue
            if post.created_at and post.created_at.replace(tzinfo=post.created_at.tzinfo or timezone.utc) < since:
                continue
            out.append((pr, {"url": post.url, "source": post.source, "date": post.created_at.date().isoformat() if post.created_at else "",
                             "engagement": post.engagement, "author": post.author}))
        return out

    def analyse(self, corpus: list[tuple[Problem, dict]], now: datetime) -> list[ThemeReport]:
        if not corpus:
            log.warning("no problems in corpus; nothing to analyse")
            return []
        cap = self.cfg.max_cluster_problems
        if len(corpus) > cap:
            # Keep the most painful, most recent, most engaged problems; log what is dropped.
            total = len(corpus)
            corpus = sorted(corpus, key=lambda pm: (pm[0].intensity, pm[1]["date"], pm[1]["engagement"]), reverse=True)[:cap]
            log.warning("cap: clustering top %d of %d problems (max_cluster_problems)", cap, total)
            self.stats["cluster_dropped"] = total - cap
        problems = [p for p, _ in corpus]
        try:
            themes = self.clusterer.cluster(problems)
        except Exception as e:
            log.error("clusterer failed (%s); falling back to one theme per segment", e)
            themes = self._segment_themes(problems)
        self.stats["themes"] = len(themes)
        recent_cut = (now - timedelta(days=30)).date().isoformat()

        def one(theme):
            ev = []
            for i in theme.problem_indexes:
                p, meta = corpus[i]
                ev.append({**meta, "quote": p.quote, "problem": p.problem, "persona": p.persona,
                           "intensity": p.intensity, "wtp_signal": p.wtp_signal, "workaround": p.workaround,
                           "first_person": p.first_person})
            ev.sort(key=lambda e: (e["intensity"], e["engagement"]), reverse=True)
            ev_text = "\n".join(
                f"- [{e['source']} {e['date']}] {e['persona']}: \"{e['quote'][:400]}\" ({e['url']})"
                + (f" WTP: {e['wtp_signal']}" if e["wtp_signal"] else "")
                for e in ev[:25]
            )
            rep = ThemeReport(theme=theme, evidence=ev)
            try:
                rep.assessment = self.analyst.assess(theme, ev_text)
            except Exception as e:
                log.warning("analyst failed for %s: %s", theme.id, e)
            try:
                rep.verdicts = self.skeptics.judge(theme, ev_text, rep.assessment)
            except Exception as e:
                log.warning("skeptic panel failed for %s: %s", theme.id, e)
            if rep.verdicts:
                rep.survives = sum(v.survives for v in rep.verdicts) * 2 > len(rep.verdicts)
            if rep.assessment:
                rep.opportunity_score = opportunity_score(rep.assessment.scores, len({e["url"] for e in ev}))
            rep.evidence = [{**e, "recent": e["date"] >= recent_cut} for e in ev]
            if self.gap and rep.assessment and (rep.survives or not self.cfg.gap_only_survivors):
                known = [s.name for s in rep.assessment.existing_solutions]
                rep.gap = self.gap.assess(theme, rep.assessment.scores, known,
                                          now - timedelta(days=self.cfg.lookback_days)).model_dump()
            return rep

        with ThreadPoolExecutor(4) as ex:
            reports = list(ex.map(one, themes))
        reports.sort(key=lambda r: (r.survives, r.gap.get("gap_score", -1), r.opportunity_score), reverse=True)
        self.stats["themes_surviving"] = sum(r.survives for r in reports)
        self.stats["quadrants"] = {}
        for r in reports:
            q = r.gap.get("quadrant")
            if q:
                self.stats["quadrants"][q] = self.stats["quadrants"].get(q, 0) + 1
        return reports

    @staticmethod
    def _segment_themes(problems: list[Problem]):
        from .models import Theme
        groups: dict[str, list[int]] = {}
        for i, p in enumerate(problems):
            groups.setdefault(p.segment or "other", []).append(i)
        return [Theme(id=s, title=f"Unclustered: {s}", problem=f"Problems in segment {s}", who_has_it="various",
                      problem_indexes=idx) for s, idx in groups.items()]

    # ---------------- entrypoint ----------------
    def run(self, now: datetime | None = None, collect: bool = True) -> tuple[str, list[ThemeReport]]:
        now = now or datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%dT%H%M%SZ")
        self.store.start_run(run_id, now.isoformat())
        if collect:
            self.collect(self.plan(), run_id, now)
        self.extract(run_id)
        reports = self.analyse(self.corpus(now), now)
        self.stats["llm_usage"] = dict(self.llm.usage)
        return run_id, reports
