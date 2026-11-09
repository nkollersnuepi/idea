"""Load radar.toml with defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ThemeSeed:
    name: str
    seed: str


@dataclass
class Config:
    lookback_days: int = 120
    max_posts_per_query: int = 25
    max_posts_total: int = 1500
    max_cluster_problems: int = 600
    min_intensity: int = 2
    db_path: str = "radar.db"
    report_dir: str = "reports"

    model_default: str = "claude-opus-5-5"
    model_extractor: str = "claude-opus-5-5"
    extractor_effort: str = "low"
    planner_effort: str = "medium"
    clusterer_effort: str = "high"
    analyst_effort: str = "high"
    skeptic_effort: str = "high"
    skeptics_per_theme: int = 3

    sources: list[str] = field(default_factory=lambda: ["hackernews", "reddit", "github", "stackexchange", "bluesky", "web"])
    reddit_subreddits: list[str] = field(default_factory=lambda: ["LocalLLaMA", "ClaudeAI", "AI_Agents"])
    stackexchange_sites: list[str] = field(default_factory=lambda: ["stackoverflow"])
    github_query_suffix: str = "is:issue created:>{since}"
    web_searches_per_theme: int = 4

    themes: list[ThemeSeed] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg = cls()
        p = Path(path) if path else Path("radar.toml")
        if not p.exists():
            return cfg
        raw = tomllib.loads(p.read_text())
        run = raw.get("run", {})
        models = raw.get("models", {})
        src = raw.get("sources", {})
        for k in ("lookback_days", "max_posts_per_query", "max_posts_total", "max_cluster_problems", "min_intensity", "db_path", "report_dir"):
            if k in run:
                setattr(cfg, k, run[k])
        if "default" in models:
            cfg.model_default = models["default"]
        if "extractor" in models:
            cfg.model_extractor = models["extractor"]
        for k in ("extractor_effort", "planner_effort", "clusterer_effort", "analyst_effort", "skeptic_effort", "skeptics_per_theme"):
            if k in models:
                setattr(cfg, k, models[k])
        if "enabled" in src:
            cfg.sources = src["enabled"]
        for k in ("reddit_subreddits", "stackexchange_sites", "github_query_suffix", "web_searches_per_theme"):
            if k in src:
                setattr(cfg, k, src[k])
        cfg.themes = [ThemeSeed(t["name"], t["seed"]) for t in raw.get("themes", [])]
        return cfg
