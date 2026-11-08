"""Render a run as Markdown, JSON and a self-contained HTML page."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .models import ThemeReport


def _delta(reports: list[ThemeReport], previous: dict | None) -> dict[str, str]:
    if not previous:
        return {}
    prev = {t["theme"]["id"]: t.get("opportunity_score", 0) for t in previous.get("themes", [])}
    out = {}
    for r in reports:
        if r.theme.id not in prev:
            out[r.theme.id] = "NEW"
        else:
            d = r.opportunity_score - prev[r.theme.id]
            out[r.theme.id] = f"{d:+.1f}" if abs(d) >= 0.5 else "="
    return out


def to_dict(run_id: str, reports: list[ThemeReport], stats: dict) -> dict:
    return {"run_id": run_id, "stats": stats, "themes": [r.model_dump() for r in reports]}


def markdown(run_id: str, reports: list[ThemeReport], stats: dict, previous: dict | None = None) -> str:
    delta = _delta(reports, previous)
    alive = [r for r in reports if r.survives]
    dead = [r for r in reports if not r.survives]
    L = [f"# Agentic Transition Problem Radar — {run_id}", ""]
    L.append(f"Sources: {json.dumps(stats.get('sources', {}))}  ")
    L.append(f"Posts read: {stats.get('posts_extracted', 0)} · new problems: {stats.get('problems_new', 0)} · "
             f"themes: {stats.get('themes', 0)} · survived skeptics: {len(alive)}")
    L += ["", "## Ranked opportunities", "", "| # | Theme | Score | Δ | Evidence | Recent 30d | Pain | WTP | Gap |", "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(alive, 1):
        s = r.assessment.scores if r.assessment else None
        L.append(f"| {i} | {r.theme.title} | {r.opportunity_score} | {delta.get(r.theme.id, '')} | {len(r.evidence)} | "
                 f"{sum(e.get('recent', False) for e in r.evidence)} | {s.pain if s else '-'} | "
                 f"{s.willingness_to_pay if s else '-'} | {s.solution_gap if s else '-'} |")
    for i, r in enumerate(alive, 1):
        a = r.assessment
        L += ["", f"### {i}. {r.theme.title}  (score {r.opportunity_score})", "", r.theme.problem, "",
              f"**Who has it:** {r.theme.who_has_it}"]
        if a:
            L += [f"**Who pays:** {a.who_pays}", f"**Why now:** {a.why_now}", f"**Opportunity:** {a.opportunity}",
                  f"**Investable angle:** {a.investable_angle}", "", "**Existing solutions & gaps:**"]
            L += [f"- {s.name}: {s.what} — *gap:* {s.gap}" for s in a.existing_solutions] or ["- none found"]
        if r.verdicts:
            L += ["", "**Skeptic panel:** " + " | ".join(f"{'✓' if v.survives else '✗'} {v.strongest_objection}" for v in r.verdicts)]
        L += ["", "**Voices:**"]
        for e in r.evidence[:8]:
            L.append(f"- \"{e['quote'][:280]}\" — {e['persona']}, {e['source']} {e['date']} ([link]({e['url']}))")
    if dead:
        L += ["", "## Killed by skeptic panel", ""]
        L += [f"- {r.theme.title} — {r.verdicts[0].strongest_objection if r.verdicts else ''}" for r in dead]
    L += ["", f"_LLM usage: {stats.get('llm_usage', {})}_", ""]
    return "\n".join(L)


def html_page(md_text: str, run_id: str) -> str:
    """Minimal standalone HTML wrapper (Markdown rendered client-side with a pinned library)."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Problem Radar {html.escape(run_id)}</title>
<style>:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e5e5e5}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--muted:#999;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;max-width:980px;margin:0 auto;padding:16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}}
a{{color:inherit}}h3{{margin-top:2em;border-top:1px solid var(--line);padding-top:1em}}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script></head>
<body><div id="c"></div><script id="md" type="text/markdown">{html.escape(md_text)}</script>
<script>const t=document.createElement('textarea');t.innerHTML=document.getElementById('md').textContent;
document.getElementById('c').innerHTML=marked.parse(t.value);</script></body></html>"""


def write(run_id: str, reports: list[ThemeReport], stats: dict, out_dir: str, previous: dict | None = None) -> dict:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    md = markdown(run_id, reports, stats, previous)
    data = to_dict(run_id, reports, stats)
    paths = {"md": d / f"{run_id}.md", "json": d / f"{run_id}.json", "html": d / f"{run_id}.html"}
    paths["md"].write_text(md)
    paths["json"].write_text(json.dumps(data, indent=2, default=str))
    paths["html"].write_text(html_page(md, run_id))
    (d / "latest.md").write_text(md)
    return {k: str(v) for k, v in paths.items()}
