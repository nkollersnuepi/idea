"""Command-line entrypoint: `radar run | collect | analyze | sources`."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from . import report
from .agents import LLM
from .config import Config
from .pipeline import Pipeline
from .sources import build_sources
from .store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="radar", description="Find unsolved problems of the agentic transition.")
    ap.add_argument("command", choices=["run", "collect", "analyze", "sources"])
    ap.add_argument("-c", "--config", default="radar.toml")
    ap.add_argument("--sources", help="comma-separated override, e.g. hackernews,reddit")
    ap.add_argument("--themes", help="comma-separated theme names to restrict to")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(name)s %(message)s")

    cfg = Config.load(a.config)
    if a.sources:
        cfg.sources = a.sources.split(",")
    if a.themes:
        keep = set(a.themes.split(","))
        cfg.themes = [t for t in cfg.themes if t.name in keep]

    if a.command == "sources":
        since = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
        if not a.sources:  # the web agent costs Claude calls; probe it only when asked explicitly
            cfg.sources = [s for s in cfg.sources if s != "web"]
        for s in build_sources(cfg, LLM() if "web" in cfg.sources else None):
            try:
                got = s.search("AI agent", since, 3)
                print(f"{s.name:14} {'OK   ' if got else 'EMPTY'} {len(got)} posts")
            except Exception as e:
                print(f"{s.name:14} FAIL  {type(e).__name__}: {e}")
        return 0

    llm = LLM()
    store = Store(cfg.db_path)
    pipe = Pipeline(cfg, llm, build_sources(cfg, llm), store)
    now = datetime.now(timezone.utc)

    if a.command == "collect":
        rid = now.strftime("%Y%m%dT%H%M%SZ")
        store.start_run(rid, now.isoformat())
        n = pipe.collect(pipe.plan(), rid, now)
        print(f"{n} new posts stored")
        return 0

    run_id, reports = pipe.run(now, collect=(a.command == "run"))
    prev = store.previous_report(run_id)
    paths = report.write(run_id, reports, pipe.stats, cfg.report_dir, prev)
    store.finish_run(run_id, datetime.now(timezone.utc).isoformat(), pipe.stats, report.to_dict(run_id, reports, pipe.stats))
    print("\n".join(f"{k}: {v}" for k, v in paths.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
