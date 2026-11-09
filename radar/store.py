"""SQLite persistence: posts are deduped across runs so momentum can be measured over time."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Post, Problem

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  uid TEXT PRIMARY KEY, source TEXT, external_id TEXT, url TEXT, author TEXT,
  title TEXT, text TEXT, created_at TEXT, engagement INTEGER, query TEXT,
  first_seen_run TEXT
);
CREATE TABLE IF NOT EXISTS problems (
  post_uid TEXT, run_id TEXT, data TEXT, problem_hash TEXT,
  PRIMARY KEY (post_uid, problem_hash)
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, stats TEXT, report TEXT
);
CREATE TABLE IF NOT EXISTS extracted (post_uid TEXT PRIMARY KEY, run_id TEXT);
"""


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    # ---- posts ----
    def add_posts(self, posts: list[Post], run_id: str) -> list[Post]:
        """Insert posts; return only those not seen before."""
        fresh = []
        for p in posts:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (p.uid, p.source, p.external_id, p.url, p.author, p.title, p.text,
                 p.created_at.isoformat() if p.created_at else None, p.engagement, p.query, run_id),
            )
            if cur.rowcount:
                fresh.append(p)
        self.db.commit()
        return fresh

    def unextracted_posts(self, limit: int, since: datetime | None = None) -> list[Post]:
        """Pending posts, round-robin across sources (newest, then most engaged, first) so no source starves."""
        rows = self.db.execute(
            "SELECT source, external_id, url, author, title, text, created_at, engagement, query FROM posts "
            "WHERE uid NOT IN (SELECT post_uid FROM extracted) "
            "ORDER BY first_seen_run DESC, created_at DESC, engagement DESC"
        ).fetchall()
        by_source: dict[str, list] = {}
        cutoff = since.isoformat() if since else None
        for r in rows:
            if cutoff and r[6] and r[6] < cutoff:
                continue  # aged out of the window; never worth paying to extract
            by_source.setdefault(r[0].split(":")[0], []).append(r)
        picked, queues = [], [q for q in by_source.values()]
        while len(picked) < limit and any(queues):
            for q in queues:
                if q and len(picked) < limit:
                    picked.append(q.pop(0))
        return [
            Post(source=r[0], external_id=r[1], url=r[2], author=r[3], title=r[4], text=r[5],
                 created_at=datetime.fromisoformat(r[6]) if r[6] else None, engagement=r[7], query=r[8])
            for r in picked
        ]

    def count_unextracted(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM posts WHERE uid NOT IN (SELECT post_uid FROM extracted)").fetchone()[0]

    def post(self, uid: str) -> Post | None:
        r = self.db.execute(
            "SELECT source, external_id, url, author, title, text, created_at, engagement, query FROM posts WHERE uid=?", (uid,)
        ).fetchone()
        if not r:
            return None
        return Post(source=r[0], external_id=r[1], url=r[2], author=r[3], title=r[4], text=r[5],
                    created_at=datetime.fromisoformat(r[6]) if r[6] else None, engagement=r[7], query=r[8])

    # ---- problems ----
    def mark_extracted(self, uids: list[str], run_id: str) -> None:
        self.db.executemany("INSERT OR IGNORE INTO extracted VALUES (?,?)", [(u, run_id) for u in uids])
        self.db.commit()

    def add_problems(self, problems: list[Problem], run_id: str) -> None:
        import hashlib
        self.db.executemany(
            "INSERT OR IGNORE INTO problems (post_uid, run_id, data, problem_hash) VALUES (?,?,?,?)",
            [(p.post_uid, run_id, p.model_dump_json(), hashlib.sha1(p.problem.encode()).hexdigest()[:12]) for p in problems],
        )
        self.db.commit()

    def problems(self, since_run: str | None = None) -> list[tuple[str, Problem]]:
        q = "SELECT run_id, data FROM problems"
        rows = self.db.execute(q).fetchall()
        return [(r[0], Problem.model_validate_json(r[1])) for r in rows if since_run is None or r[0] >= since_run]

    # ---- runs ----
    def start_run(self, run_id: str, started_at: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)", (run_id, started_at, None, None, None))
        self.db.commit()

    def finish_run(self, run_id: str, finished_at: str, stats: dict, report: dict) -> None:
        self.db.execute(
            "UPDATE runs SET finished_at=?, stats=?, report=? WHERE run_id=?",
            (finished_at, json.dumps(stats), json.dumps(report, default=str), run_id),
        )
        self.db.commit()

    def previous_report(self, run_id: str) -> dict | None:
        r = self.db.execute(
            "SELECT report FROM runs WHERE run_id < ? AND report IS NOT NULL ORDER BY run_id DESC LIMIT 1", (run_id,)
        ).fetchone()
        return json.loads(r[0]) if r else None
