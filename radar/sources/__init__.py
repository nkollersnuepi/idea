from .base import Source
from .bluesky import Bluesky
from .github import GitHub
from .hackernews import HackerNews
from .reddit import Reddit
from .stackexchange import StackExchange
from .web import WebAgent


def build_sources(cfg, llm) -> list[Source]:
    registry = {
        "hackernews": lambda: HackerNews(),
        "reddit": lambda: Reddit(cfg.reddit_subreddits),
        "github": lambda: GitHub(cfg.github_query_suffix),
        "stackexchange": lambda: StackExchange(cfg.stackexchange_sites),
        "bluesky": lambda: Bluesky(),
        "web": lambda: WebAgent(llm, cfg.model_default, "medium", cfg.web_searches_per_theme),
    }
    unknown = set(cfg.sources) - set(registry)
    if unknown:
        raise ValueError(f"unknown sources in config: {sorted(unknown)}")
    return [registry[n]() for n in cfg.sources]


__all__ = ["Source", "build_sources", "HackerNews", "Reddit", "GitHub", "StackExchange", "Bluesky", "WebAgent"]
