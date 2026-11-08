"""Offline tests: fake LLM + fake sources exercise the full pipeline; parsers run on fixture JSON."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from radar import report
from radar.config import Config, ThemeSeed
from radar.models import (Assessment, ExistingSolution, ExtractionBatch, Post, Problem, QueryPlan, Scores,
                          SkepticVerdict, Theme, ThemeSet, opportunity_score)
from radar.pipeline import Pipeline
from radar.sources import base as src_base
from radar.sources.base import Source
from radar.store import Store

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


class FakeLLM:
    usage = {"calls": 0}

    def __init__(self, refute: bool = False):
        self.refute = refute
        self.seen_users: list[str] = []

    def research(self, **kw):
        return "notes: competitor X https://example.com"

    def structured(self, *, schema, user, **kw):
        self.seen_users.append(user)
        if schema is QueryPlan:
            return QueryPlan(queries=["agent broke prod", "mcp oauth pain"])
        if schema is ExtractionBatch:
            import re
            uids = re.findall(r'uid="([0-9a-f]+)"', user)
            return ExtractionBatch(problems=[
                Problem(post_uid=u, is_problem=True, problem=f"problem for {u}", quote="it broke", persona="dev",
                        segment="coding-agents", intensity=4, wtp_signal="we pay $500/mo", workaround="", first_person=True)
                for u in uids
            ] + [Problem(post_uid="bogus", is_problem=True, problem="hallucinated uid", quote="", persona="", segment="x",
                         intensity=5, wtp_signal="", workaround="", first_person=True)])
        if schema is ThemeSet:
            n = user.count("\n[")  # problem lines
            return ThemeSet(themes=[
                Theme(id="t1", title="Agents break prod", problem="p", who_has_it="devs", problem_indexes=list(range(n + 1)) + [999]),
                Theme(id="t2", title="Duplicate theme", problem="p", who_has_it="devs", problem_indexes=[0]),
            ])
        if schema is Assessment:
            return Assessment(existing_solutions=[ExistingSolution(name="X", what="does y", gap="z")],
                              scores=Scores(pain=5, frequency=4, willingness_to_pay=4, momentum=5, solution_gap=4, market_size=3),
                              why_now="agents in prod", who_pays="eng leads", opportunity="build it", investable_angle="DDOG")
        if schema is SkepticVerdict:
            return SkepticVerdict(survives=not self.refute, strongest_objection="maybe solved", confidence=3)
        raise AssertionError(schema)


class FakeSource(Source):
    name = "fake"

    def search(self, query, since, limit):
        return [Post(source="fake", external_id=f"{query}-{i}", url=f"https://x/{i}", text=f"{query} text {i} " * 5,
                     created_at=NOW - timedelta(days=i * 10), engagement=i) for i in range(3)]


class BrokenSource(Source):
    name = "broken"

    def search(self, query, since, limit):
        raise ConnectionError("down")


def make_cfg(tmp_path) -> Config:
    cfg = Config(db_path=str(tmp_path / "r.db"), report_dir=str(tmp_path / "reports"))
    cfg.themes = [ThemeSeed("coding-agents", "coding agents breaking"), ThemeSeed("mcp", "mcp auth")]
    return cfg


def test_full_pipeline(tmp_path):
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    llm = FakeLLM()
    pipe = Pipeline(cfg, llm, [FakeSource(), BrokenSource()], store)
    run_id, reports = pipe.run(NOW)
    assert pipe.stats["sources"]["broken"] == {"fetched": 0, "new": 0}  # failing source isolated
    assert pipe.stats["sources"]["fake"]["new"] == 6  # 2 unique queries x 3 posts (deduped across themes)
    assert pipe.stats["problems_new"] == 6  # bogus uid dropped
    t1 = next(r for r in reports if r.theme.id == "t1")
    assert len(t1.evidence) == 6  # out-of-range index 999 dropped
    # t2 only had index 0 which t1 already claimed -> dropped
    assert all(r.theme.id != "t2" for r in reports)
    assert t1.survives and t1.opportunity_score > 50
    paths = report.write(run_id, reports, pipe.stats, cfg.report_dir)
    md = open(paths["md"]).read()
    assert "Agents break prod" in md and "Voices" in md
    assert "<!doctype html>" in open(paths["html"]).read()


def test_rerun_is_incremental(tmp_path):
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    Pipeline(cfg, FakeLLM(), [FakeSource()], store).run(NOW)
    p2 = Pipeline(cfg, FakeLLM(), [FakeSource()], store)
    p2.run(NOW + timedelta(days=1))
    assert p2.stats["sources"]["fake"]["new"] == 0
    assert p2.stats["posts_extracted"] == 0  # nothing re-extracted
    assert p2.stats["themes"] >= 1  # still analyses the stored corpus


def test_skeptic_majority_kills(tmp_path):
    cfg = make_cfg(tmp_path)
    pipe = Pipeline(cfg, FakeLLM(refute=True), [FakeSource()], Store(cfg.db_path))
    _, reports = pipe.run(NOW)
    assert reports and not any(r.survives for r in reports)
    assert "Killed by skeptic panel" in report.markdown("r", reports, pipe.stats)


def test_lookback_filters_old_posts(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.lookback_days = 15  # only the day-0 and day-10 posts qualify
    pipe = Pipeline(cfg, FakeLLM(), [FakeSource()], Store(cfg.db_path))
    pipe.run(NOW)
    assert len(pipe.corpus(NOW)) == 4


def test_score_bounds():
    lo = opportunity_score(Scores(pain=1, frequency=1, willingness_to_pay=1, momentum=1, solution_gap=1, market_size=1), 0)
    hi = opportunity_score(Scores(pain=5, frequency=5, willingness_to_pay=5, momentum=5, solution_gap=5, market_size=5), 50)
    assert lo == 0 and hi == 100


def test_config_loads_repo_file():
    cfg = Config.load("radar.toml")
    assert len(cfg.themes) >= 10 and "hackernews" in cfg.sources


# ---------------- source parsers on fixture payloads ----------------

@pytest.fixture
def fake_http(monkeypatch):
    def install(payload):
        monkeypatch.setattr(src_base, "get_json", lambda *a, **k: payload)
        for mod in ("hackernews", "reddit", "github", "stackexchange", "bluesky"):
            m = __import__(f"radar.sources.{mod}", fromlist=["get_json"])
            monkeypatch.setattr(m, "get_json", lambda *a, **k: payload)
    return install


SINCE = NOW - timedelta(days=365)


def test_hn_parser(fake_http):
    from radar.sources.hackernews import HackerNews
    fake_http({"hits": [{"objectID": "1", "comment_text": "<p>Our agent &amp; MCP setup keeps leaking tokens to logs every day</p>",
                         "author": "a", "created_at_i": 1790000000, "points": None, "num_comments": None}]})
    p = HackerNews().search("q", SINCE, 5)[0]
    assert "&" in p.text and "<p>" not in p.text and p.url.endswith("id=1")


def test_reddit_parser(fake_http):
    from radar.sources.reddit import Reddit
    fake_http({"data": {"children": [
        {"data": {"id": "a", "permalink": "/r/x/a", "title": "t", "selftext": "s", "created_utc": 1790000000, "score": 3, "num_comments": 2}},
        {"data": {"id": "old", "permalink": "/r/x/o", "title": "t", "selftext": "s", "created_utc": 1000, "score": 3, "num_comments": 2}},
    ]}})
    r = Reddit(["x"])
    r_posts = r.search("q", SINCE, 5)
    assert [p.external_id for p in r_posts] == ["a"] and r_posts[0].engagement == 5


def test_github_parser(fake_http):
    from radar.sources.github import GitHub
    fake_http({"items": [{"id": 9, "html_url": "https://github.com/o/r/issues/1", "user": {"login": "u"}, "title": "t",
                          "body": None, "created_at": "2026-10-01T00:00:00Z", "comments": 4, "reactions": {"total_count": 6}}]})
    p = GitHub().search("q", SINCE, 5)[0]
    assert p.engagement == 10 and p.text == ""


def test_stackexchange_parser(fake_http):
    from radar.sources.stackexchange import StackExchange
    fake_http({"items": [{"question_id": 5, "link": "https://so/q/5", "title": "a &amp; b", "body": "<p>x</p>",
                          "creation_date": 1790000000, "score": 1, "answer_count": 0, "view_count": 250}]})
    p = StackExchange(["stackoverflow"]).search("q", SINCE, 5)[0]
    assert p.title == "a & b" and p.engagement == 3


def test_bluesky_parser(fake_http):
    from radar.sources.bluesky import Bluesky
    fake_http({"posts": [{"uri": "at://did:plc:x/app.bsky.feed.post/abc", "author": {"handle": "h.bsky.social"},
                          "record": {"text": "agents", "createdAt": "2026-10-01T00:00:00.000Z"}, "likeCount": 2}]})
    p = Bluesky().search("q", SINCE, 5)[0]
    assert p.url == "https://bsky.app/profile/h.bsky.social/post/abc"
