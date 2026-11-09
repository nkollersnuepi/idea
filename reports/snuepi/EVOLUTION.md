# snuepi → Kept: best problem and evolution plan, checked against the code (2026-11-09)

**How this was made:**
- 6 agents read the snuepi code at `e1708b9`, area by area.
- One agent re-ranked the candidate products using code reuse that was actually checked.
- One agent searched for a better problem than Kept.
- One agent wrote the plan.
- One agent verified the plan's code references: 91% held, and its corrections are folded in below.
- Raw output: `2026-11-09-code-evolution-workflow.json`.

## 1. The problem to solve

> An agency runs Vapi, Retell or GHL receptionists for 3–40 small-business clients. Today it cannot tell, call by call, whether what its agent told a caller was true:
> - **"You're booked Tue 14:30":** does the booking exist, at that time and in that zone, not in the past and not double-booked?
> - **"That's €65":** is that the listed price for the service?
> - **"20% off for first-timers":** do the client's rules allow that discount?
> - **"Free cancellation until tomorrow":** is that the client's policy?
>
> Errors surface only when a customer turns up, or when the owner complains and the agency loses the retainer.

**Kept** reports every false or unbacked commitment within 5 minutes of the call. A commitment fails in one of two ways:
- **(a) Unbacked by the agent's own tool calls.** This is checked from the call logs alone, with no client access.
- **(b) Unbacked by the client's system of record at that moment.** This is checked against the calendar plus the price and rule set, which are snapshotted and signed.

Each month Kept also produces a white-label proof report per client.

**North-star metric:** uncaught wrong commitments per 100 booking calls. It is weighted toward **price, discount and policy errors**, because the platforms will absorb the time-of-day errors.

## 2. Ranking with checked code reuse

| Candidate | Demand | Will pay | Code reuse | Platform absorbs (5 = likely) | Weeks to first revenue | Scale | Verdict |
|---|---|---|---|---|---|---|---|
| **Kept, observing first, live gate as a later upsell** | 4 | 3 | 3 | 3 | 8 | 4 | **Best** |
| Kept, post-call only | 4 | 3 | 3 | 3 | 8 | 3 | Ceiling too low on its own |
| Live gate alone | 3 | 3 | 4 | 4 | 12 | 3 | Most reuse, wrong first move (call-path liability, lock in one process) |
| Agent-reachability monitor | 3 | 2 | 4 | 5 | 6 | 2 | Free lead tool at most |
| Insurer ledger | 2 | 4 | 3 | 2 | 40 | 5 | The long-term endgame, no data yet |
| Dispute pack | 1 | 2 | 2 | 5 | 30 | 2 | Park it |

**The alternatives challenge: nothing beat Kept.** It checked four alternatives:
- **A live no-double-booking tool:** already sold cheaply (Temporal Cortex, Cronofy, Nylas, Cal.com). It becomes Kept's live gate later.
- **A monitor for AI assistants stating wrong hours:** crowded (Yext, Uberall, Profound, Peec).
- **An EU chatbot-statement guard:** no first-person demand. It becomes Kept's stage 3.
- **Salon double-booking across marketplaces:** the marketplace APIs are closed.

## 3. What the code changed in the plan

1. **The reply guard cannot be the extractor.** It is a regex sanitiser with **no tests**. Checked false positives:
   - it fires on negations and questions ("I haven't booked anything yet");
   - it misses "scheduled" and $ or £ amounts;
   - it reads "1.000" as 1.

   Extraction must be a new structured-LLM step. Snuepi's fixed code only judges.
2. **The cheapest strong signal needs no client access.** Vapi and Retell end-of-call payloads include the agent's tool calls and their results. That catches two errors from the logs alone:
   - "said booked, but the booking tool failed or was never called";
   - "quoted a price the tool never returned".

   This removes the biggest friction in the audit.
3. **The valuable reusable core is small and good:** `time.mjs`, `opening-hours.mjs`, `beregnPris`, `mandate.forhandle`, the `ikkeLedig` reason codes, connector auth and refresh, and the signing core. About 600 solid lines.
4. **The connectors need work before they can be ground truth:**
   - they return only id, start and end;
   - `sync.mjs:114` deletes history on every sync;
   - Cal.com hides past bookings.

   Kept must read on demand for each call and store a hashed snapshot.

## 4. Bugs to fix first (all confirmed in the code)

| Where | Bug | Why it matters for Kept |
|---|---|---|
| `src/time.mjs:6`, `src/agent-ready.mjs` (25 imports + db) | The time logic and `beregnPris` can't load without the database | Lift the pure parts into `kept/kernel/` first. Note: connectors also reach the database through `time.mjs` and `connection.mjs`, so they need `npm ci` and better-sqlite3 too |
| `src/time.mjs#tilMs` | Inconsistent DST handling: a repeated hour resolves later in Oslo but earlier in New York; a skipped hour shifts forward in UTC+ zones and back in UTC− zones | Wrong verdicts around clock changes |
| `src/time.mjs:9-13` `LAND_SONE` | Covers only the EU, GB and CH | US clients silently get the server's time zone |
| `src/intake.mjs#lesTidspunkt` (~l.100) | Always reads day first, so the US date "11/07/2026" becomes 11 July | Wrong dates for US agencies |
| `src/catalog-import.mjs#tall` (l.13) | Recognises only kr/NOK, so "€35" and "$1,234.50" become NaN and the row is silently dropped | Breaks price checks against real price lists |
| `src/integrations/calcom.mjs:78` | Reads only upcoming and unconfirmed bookings | Every past booking looks "not found" |
| `google.mjs:52`, `microsoft.mjs:44` | Silently stop after 5 pages of results | False "missing" verdicts |
| `src/agent-ready.mjs:285,327` / `:276,305` | Adds up overlapping bookings instead of checking peak concurrency; start times hard-coded to the hour | False "full"; the double-booking check needs a new function |
| `src/proof.mjs:38-44` | Falls back to generating the private signing key into SQLite, which Litestream then replicates | Refuse that fallback in production; require `SIGNING_KEY_PEM`, which the code already supports |
| `src/config.mjs:28` | Login is switched off by default outside production | Today's Fly configs set production, but any new deploy that omits it opens the console to everyone |
| `src/mandate.mjs` | The discount vocabulary can't express first-visit, student or promo-code offers | Kept would flag legitimate promises; a promo rule set is needed |
| `src/onboarding.mjs:139` | Service length hard-coded to 60 minutes | Wrong durations when the website reader is the source of truth |

## 5. Evolution plan (carve `kept/` out of the repo; no rewrite, no fork of `server.mjs`)

### Stage 0: logs-only audit tool (9 Nov → 8 Dec, Gate A), about 5 days to build
- **New files:**
  - `kept/kernel/time.mjs`: `tilMs`/`vegg` with the zone passed in, without the database import, plus `validateWallClock`.
  - `kept/kernel/pricing.mjs`: `valgFor`, `lesValg` and `beregnPris` lifted from `agent-ready.mjs:91-142`, with replacements for `J`, `AppError` and `badRequest`.
  - `kept/ingest/vapi.mjs` and `kept/ingest/retell.mjs`.
  - `kept/extract.mjs`: a structured LLM step through `src/llm.mjs#chat`.
  - `kept/rules/index.mjs`: rules R1–R8, written as pure functions.
  - `scripts/kept-audit.mjs`: outputs `report.html`, `mismatches.csv`, and errors per 100 booking calls.
  - 30+ labelled simulated test calls.
- **Changes:**
  - `src/llm.mjs`: add a `tool_choice` option. It is hard-coded to `auto` at line 76 today.
  - `catalog-import.mjs#tall`: parse currency symbols and thousands separators.
  - Lead engine: retarget `scripts/collectors/config.json`, the seeds, `prefilter.mjs`, and the `PAINS` list in `signals-brief.mjs` to agency booking threads.
- **Gate A:**
  - 25 calls;
  - at least 10 audits agreed and at least 5 delivered;
  - at least 80% of flags confirmed as real errors when you review them by hand;
  - ask on every call whether they want errors **prevented or detected**.

### Stage 0.5: concierge audits with the calendar, sell the pilot (9 Dec → 8 Jan, Gate B), about 4 days
- **Calendar check:** add `--calendar google|microsoft|ical|calcom|square` and rule R9 (booking missing, at a different time, or double-booked). R9 uses the existing connectors' `hentOpptatt` window reads; for Square that is the internal `hentOpptatt`, not `hentBestillinger`.
- **Fixes:** Cal.com past bookings, Google/Microsoft silent truncation, and Microsoft error status. Plus a date-order option in `lesTidspunkt`.
- **New files:**
  - `kept/match.mjs`: matches within ±15 minutes, tolerating time-zone differences.
  - `kept/kernel/slots-check.mjs`: peak concurrency.
  - `docs/kept/pilot-contract.md`.
- **Gate B:** at least 1 signed, priced pilot. **The build starts only after that signature.**

### Stage 1: Kept v1, the observer product (first signature + 6 weeks, about 22 Feb 2027), about 30 days
- **The service:** `kept/server.mjs`, a slim server with about 25 routes. Fresh `kept/migrations` with about 10 English tables.
- **Ingest and connectors:** Vapi and Retell webhooks with signature checks and no double-processing. A new GHL connector. An event-detail read added to each connector.
- **Verification:** `kept/snapshot.mjs` stores a sha256 of the source data. The ledger is extracted from `record-log.mjs#leggTil`. A promo rule set is added. A verification worker runs 2–4 minutes after each call.
- **Output:** alerts by email or webhook (Slack is new; the code has none today), a static console, and the white-label report.
- **Reused:** `src/db.mjs`, the `auth.mjs` building blocks, the `agent-identity.mjs` key pattern, `proof.mjs` signing, `record-log-merkle.mjs` and `-roots.mjs`, `mail.mjs`, and the share-link pattern from `report.mjs`.
- **Security fixes before any agency logs in:** the `proof.mjs` key fallback, `config.mjs:28`, and enabling TSA timestamps.
- **Gate to stage 2:**
  - at least 3 paying agencies and at least 30 clients monitored;
  - at least 90% precision;
  - no pilot churn in the first 60 days;
  - at least 2 agencies ask in writing for prevention.

### Stage 2: live "verify then book" gate (about Apr–Jun 2027), about 20 days
- **What:** +€15 per client, sold only to clients whose audits show high error rates.
- **Reused:**
  - the `ikkeLedig` reason codes;
  - signed quotes, re-keyed off `sessionSecret`;
  - `mandate.forhandle`;
  - the fail-closed pattern from `table-availability.mjs`;
  - `write-back.mjs`.
- **Required first:**
  - pull a pure `slots()` out of `ledigeTider`, with a step per service and peak concurrency;
  - fix the time-offset bug at `agent-ready.mjs:968`;
  - replace the in-memory locks with a database slot-claim table.
- **Gate to stage 3:**
  - p95 under 800 ms;
  - zero double-bookings in 30 days;
  - errors down at least 70% from the client's own baseline.

### Stage 3: chat, WhatsApp and email agents; EU liability; OEM (2027 H2)
- **The EU liability angle:** OLG Hamm 4 UKl 3/25 holds the business liable for its chatbot's statements.
- **Reused:** `customer-terms.mjs` (snapshot of what the customer was shown) and `guardrails.mjs`, inverted to check what the agent says.
- **Required:** precision work in `reply-guard.mjs`.
- **OEM:** an API for white-label agency platforms.

### Stage 4: verified-outcome ledger for AI-liability insurers (2028)
- **Reused:** the versioned rule hash from `shadow-claims-rules.mjs`, the confidence-bound math (`wilson`, `betaKvantil`), the anonymisation in `loss-records.mjs`, `record-log-tsa.mjs`, and the Merkle inclusion proofs.
- **To do:** re-key everything to per-deployment agent errors, add consistency proofs and an outside anchor, and move the signing key to a KMS.

**Retire:** take these out of deployment and keep them in git:
- the doors, payments and checkout protocols, agent identity and the know-your-agent/know-your-business checks;
- the regulated-work guardrails, the world simulator and the terms registry;
- the call-legit checks;
- the 127-migration chain. Kept starts with fresh migrations.

## 6. This week
- **Mon:**
  - freeze the live deploy (Fly app `tender-nordredrift`);
  - run `npm ci` and record a test-suite baseline (it has never run in this checkout);
  - create `kept/kernel/time.mjs`.
- **Tue:**
  - `kernel/pricing.mjs` with tests;
  - the Vapi and Retell normalisers;
  - 30 labelled **simulated** test calls.
- **Wed:**
  - `extract.mjs`; iterate until at least 90% of seeded commitments are found;
  - retarget the lead engine.
- **Thu:**
  - rules R1–R8;
  - fix `tall`;
  - `scripts/kept-audit.mjs`.
- **Fri:**
  - `docs/kept/audit-offer.md` (EU processing, 30-day deletion, data processing agreement);
  - start daily outreach in the Vapi, Retell, n8n and GHL threads.
- **Weekend:**
  - triage the top 50 threads the lead engine finds;
  - finalise the Gate A call script.

## 7. Risks
- **Willingness to pay** is unproven. That is why the audits come before any build.
- **Access friction:** agencies may refuse access. Stage 0 needs exports only, and the fallback is an adversarial stress test.
- **Platform absorption:** value is weighted toward price, discount and policy checks.
- **The real error rate may be too low:** kill criterion 1.
- **Extractor false positives:** fixed-code judging plus at least 80–90% reviewed precision.
- **Prevent vs detect:** asked on every call. If most agencies want prevention, stage 2 comes forward, but only after the lock fix.
- **The connectors are beta:** Google event details need a Limited Use review, which takes weeks. There is no GHL connector yet.
- **Founder bandwidth:** keep `kept/` separate and never edit retired code.
- **GDPR:** transcripts contain personal data. Use EU processing and the EU LLM, delete after 30 days, and have a data processing agreement before the first audit.
- **US readiness:** time zones, date order, currency parsing and VAT are EU-centric. Start in the EU and UK.

## 8. Missing from the repo
- `docs/rebuild/PLAN.md` and `PORT-OR-RETIRE.md`
- the dispute-evidence branch

Push them if they should be weighed in.
