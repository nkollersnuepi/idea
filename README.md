# Agentic Transition Problem Radar

A set of AI agents that finds **unsolved problems created by the agentic transition**: the shift from people operating software to AI agents doing the work. It sources problems **from the people who have them**: complaints, help requests and incident reports on Hacker News, Reddit, GitHub, Stack Exchange, Bluesky, and the open web (X, LinkedIn, community forums, Substack). It then ranks them as investable opportunities.

## The agents

| # | Agent | What it does | Output |
|---|---|---|---|
| 1 | **Planner** | Turns each theme seed in `radar.toml` into short search queries phrased the way people complain | `QueryPlan` |
| 2 | **Collectors** | Keyword sources (HN, Reddit, GitHub, Stack Exchange, Bluesky) plus a **Web agent** (Claude `web_search`/`web_fetch`) for channels with no API | `Post` rows in SQLite, deduplicated across runs |
| 3 | **Extractor** | Reads posts in batches of 15. Pulls out first-person problems with a verbatim quote, persona, pain level (0–5), willingness-to-pay signal and current workaround | `Problem` |
| 4 | **Clusterer** | Merges every problem into specific themes that one product could solve | `Theme` |
| 5 | **Analyst** | Researches each theme on the web: existing solutions and their gaps, more evidence, who pays, why now, exposed companies. Scores six dimensions | `Assessment` |
| 6 | **Skeptic panel** | 3 independent refuters, each with a different lens (*already solved*, *hype not pain*, *no business*, *evidence quality*). A theme dies if a majority refute it | `SkepticVerdict` |
| 7 | **Market-gap engine** | For every surviving theme: maps existing solutions (startups, open source, incumbents, platform features) and rates each one's **coverage** of the exact problem (0–5) and **maturity**. Searches HN, Reddit and GitHub for **users complaining about those solutions**. Rates the **risk that a platform ships it for free**. A counter-agent tries to **refute the gap** by finding a solution that already covers it | `GapResult` |
| 8 | **Reporter** | Ranked Markdown, HTML and JSON reports, with score changes (Δ) against the previous run | `reports/` |

**Opportunity score (0–100):** a weighted sum of the six 1–5 scores — pain 22%, willingness to pay 22%, frequency 18%, solution gap 15%, momentum 13%, market size 10% — rescaled to 0–90. Up to +10 is added for the number of distinct sources behind a theme.

## Market gaps: problem × lack of solution

The headline output is a quadrant: is there a strong problem, and is it still unsolved?

| | Weak current solutions | Strong current solutions |
|---|---|---|
| **Strong problem** | **TRUE GAP**: build / invest | **CROWDED**: only with a sharp wedge |
| **Weak problem** | **UNDERSERVED NICHE**: watch momentum | **SOLVED**: ignore |

```
problem_strength  = pain 30% + willingness to pay 30% + frequency 25% + momentum 15%     (0–1)
solution_strength = best over solutions of coverage × maturity factor × (1 − user-complaint penalty)
                    (raised if the counter-agent finds a covering solution)              (0–1)
gap_score         = 100 × problem_strength × (1 − solution_strength) × (1 − absorption-risk discount)
```

Each theme in the report also includes a solution-landscape table, quoted user complaints about the existing tools, the uncovered **whitespace**, and the narrowest **wedge** product. The cut-offs and search budgets are set in the `[gap]` section of `radar.toml`; the math is in `radar/gap.py`.

## Run it

```bash
pip install -e ".[dev]"
```

```bash
export ANTHROPIC_API_KEY=...        # required
```

```bash
radar run                           # full pipeline → reports/<run_id>.md|.html|.json and reports/latest.md
```

```bash
radar sources                       # check each source is reachable
```

```bash
radar run --sources hackernews,reddit --themes coding-agents,mcp-and-tools
```

```bash
radar collect                       # collect only (cheap, no Claude calls except the planner and web agent)
```

```bash
radar analyze                       # re-analyse the stored corpus without collecting again
```

Optional keys (higher rate limits): `GITHUB_TOKEN`, `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`, `STACKEXCHANGE_KEY`.

Runs are incremental. Posts are stored in `radar.db` and never extracted twice. Every run clusters the whole corpus inside the lookback window, so themes pick up evidence over time and the report shows how scores move between runs.

## Configure

Edit `radar.toml`:
- **Themes:** 14 seeds ship by default — coding agents, agent reliability, MCP and tools, security and identity, enterprise adoption, agents on the web, agent commerce, small-business operators, knowledge work, cost and infra, data and context, regulated industries and liability, the labor transition, agent-to-agent.
- **Subreddits and Stack Exchange sites.**
- **Lookback window and caps.** When a cap drops posts, the run logs it; it is never silent.
- **Model and reasoning effort per agent.** The default model is `claude-opus-5-5`. Bulk extraction runs at `low` effort; analysis and skeptics run at `high`.

Claude's server-side refusal fallback (`fallbacks: "default"`) is on for every call. Set `RADAR_FALLBACKS=0` to turn it off.

## Run inside Claude Code (no API key)

`.claude/workflows/agentic-radar.js` runs the same agent design as a Claude Code workflow, using its WebSearch and WebFetch tools:
- 14 segment hunters
- a clusterer
- a verifier/scorer for each theme
- a completeness critic

In Claude Code, ask to *run the agentic-radar workflow*. `.claude/workflows/market-gap.js` runs the gap engine (solution mapper and gap skeptic) over a themes file.

## Scheduled

`.github/workflows/radar.yml` runs every Monday and commits the report to `reports/`. Add `ANTHROPIC_API_KEY` as a repository secret.

## Tests

```bash
pytest -q
```

The tests run offline: a fake LLM and fake sources drive the full pipeline, and every source parser is tested on fixture payloads.

## Layout

```
radar/
  agents/      llm.py (SDK wrapper), prompts.py, Planner/Extractor/Clusterer/Analyst/SkepticPanel
  sources/     hackernews, reddit, github, stackexchange, bluesky, web (Claude research agent)
  pipeline.py  orchestration
  store.py     SQLite corpus
  report.py    md/html/json
  cli.py       `radar` command
radar.toml     themes, sources, models
reports/       generated reports (first one: seed run from a Claude Code agent sweep)
```
