# snuepi rework: best-fit plan (2026-11-09)

**How this was made:**
- 4 targeted evidence hunts: 93 findings.
- 4 independent designs, each from a different angle.
- 3 judges: a seed investor, someone who has sold to small businesses and agencies, and an evidence auditor. All 3 independently picked the same design ("Kept"). The additions they recommended from the other designs are folded in below.
- Raw output: `2026-11-09-rework-workflow.json`.
- Caveat: almost all evidence is search snippets, and Reddit was blocked. Willingness to pay is inferred, not observed. That is why the plan below runs a test first and builds second.

## 1. Verdict on the current rebuild (the agent-purchase dispute pack)

**Park it.** 20 targeted searches found **no production case** of a merchant or payment provider fighting a chargeback on a purchase an agent placed.
- ChatGPT Instant Checkout was scaled back around March 2026 because people did not buy through it, so there is almost no volume to dispute.
- Network dispute rules and reason codes for agent purchases do not exist yet.
- Incumbents are already moving: Chargebacks911 merchant indemnity (27 Oct 2026), Visa AI dispute tools, Amex Agent Purchase Protection.
- Dispute budgets are paid as a share of money recovered (Chargeflow 25%, Disputifier 20%), not for evidence infrastructure.
- The radar's broad sweep scored the same theme lowest of all 34: pain, frequency and willingness to pay all 2/5.

## 2. The rework: **Kept**, independent verification that bookings are real, for voice-AI agencies

**One line:** after every call, Kept checks what a client's Vapi, Retell, GoHighLevel or n8n agent promised against the real calendar and price list. It alerts the agency within minutes when a "you're booked" or a quoted price is false. Each month it gives the agency a white-label report proving the bookings were real, and the agency uses that report to keep its clients.

**Why this is the best fit:**
- **The pain is documented at volume.** Vapi, Retell, n8n and Skool threads report bookings in the past or a year off, time-zone shifts, double-booking, "booked" when the webhook failed, and invented prices.
- **Vapi's own docs say** confirmation must be enforced in the builder's own service, not by the prompt.
- **Nobody sells it for small-business agents.** Testing tools (Cekura, Hamming, Coval) check builds before launch. Runtime guardrails are funded only as enterprise security.
- **Platforms don't cover it fully.** Each platform grades only its own channel, while agencies run several. They also have no incentive to tell the agency's client that their agent made mistakes.
- **The buyer is reachable and has margin.** Agencies resell receptionists at $297–$997 a month, or £750–£3,000, on top of about $0.11 a minute in platform cost.

**Buyer:** the owner of a 2–40 person voice/chat AI agency running 3–40 small-business clients. Start with the UK, DACH, the Nordics and the Benelux, then the US.

### The judges' combined design
1. **Observe first, gate later.** v1 runs after the call: one read-only API key and read access to the client's calendar. It adds no delay to live calls and no liability in the call path. A live "verify then book" tool comes in v1.5, and only if pilots ask for it after seeing their own error rates.
2. **Weight the value toward prices, discounts and policy promises.** The date and time-zone slice will be absorbed by the platforms within 12 months (Retell's time variables, GHL's claimed double-booking prevention). Commitments checked against the business's own price list and rules are what platforms don't check.
3. **Headline metric: errors per 100 calls that the agency had NOT caught.** This tests the "silent failure" thesis directly, and it is the number that converts a prospect.
4. **Sell keeping clients, not testing.** The white-label "verified bookings and value" report goes to the business owner and carries a "verified by Kept" mark, so it also spreads the product.
5. **A zero-access opener.** For agencies that won't hand over logs, offer a free stress test: about 50 adversarial calls to their live number. Only as a fallback; real-log audits are the actual test.
6. **An LLM extracts what the agent claimed, and fixed code (snuepi's engine) judges it.**

### v1 scope (6 weeks, built only after the first signed pilot)
- **Ingest call logs:** Vapi and Retell call exports or end-of-call webhooks, plus GHL.
- **Ground truth:** existing calendar connectors (Google, Microsoft, iCal, Cal.com, Acuity, Square, SimplyBook, Calendly), plus a new GHL calendar connector. The client's price list, hours and maximum discount come from snuepi's website reader.
- **Extract** the commitments: booking, reschedule, cancel, price, discount, refund.
- **Reconcile** each one: does the event exist? Right date, time and time zone? In the past, outside opening hours, or double-booked? Did a reschedule free the old slot? Is the price on the list? Is the discount within the limit?
- **Alert within 5 minutes** (email, Slack or SMS) with a fix link.
- **Agency console:** error rate per client and per type of error, with the trend after each prompt change.
- **White-label monthly report** (PDF and link).
- **Signed record:** each call's verdict goes into the signed, chained log. It is kept internal in v1 and becomes valuable later, in stage 4.

### Pricing
- **Free concierge "Booking Truth Audit"**, run by you. It is the lead offer.
- **Agency plan:** €199 a month including 5 clients, then €29 per client per month (3–6% of a typical retainer).
- **Design-partner pilot:** a 90-day signed contract with a card on file.
  - Ask **€490 a month** for up to 10 clients, credited against the first months of the full plan.
  - The evidence auditor argued that a higher price tests willingness to pay better than €249. Don't go below €249.
- **Live booking tool (v1.5):** +€15 per client.

## 3. What happens to the existing snuepi code (about 50–60% of v1 already exists)

| Keep / repurpose | Becomes |
|---|---|
| Booking engine time logic (opening hours, holidays, time zones, slot validation) | The ground-truth checker |
| Calendar and appointment connectors, sync and polling | Ground-truth sources (fix the hourly polling → read live at check time) |
| Reply-guard patterns: false "booked", promised discounts and prices, 12 languages | Extraction and flagging (from blocking to detecting) |
| Terms layer: price floors, discount rules, 9 sector defaults | The client's price list and discount policy |
| One-approval activation (website reader) | Client setup in 2 minutes |
| Signed chained record and daily fingerprint | Internal verdict log, later evidence for insurers |
| Booking and hostile-agent simulators | Synthetic regression calls and the stress-test opener |
| snuepi-signals lead engine | Finding agency threads about wrong bookings |
| LLM cost caps, EU LLM (Scaleway), Fly/SQLite/Litestream | Same infrastructure |

**New:** Vapi, Retell and GHL log ingestion, a GHL calendar connector, the commitment-extraction pipeline, alerts, the agency console and the white-label report.

**Retire** (keep in git, remove from the deployed product):
- the dispute pack;
- the payment and checkout protocols (ACP, UCP, AP2, Stripe shared payment tokens), A2A and the buyer-agent MCP server;
- OAuth customer mandates and per-business agent cards;
- the money stack;
- Web Bot Auth, know-your-agent and know-your-business checks, fake-brand detection and trust levels;
- the phone, email, booking-page and widget doors;
- the regulated-work guardrails;
- the world simulator;
- the terms registry and the Agent Terms standard (park them in a public repo);
- the partner-gated and restaurant connectors;
- the Norway leftovers.

Target size: about 25 routes, down from 444.

## 4. Validation, using your existing gates

**This week:**
- Freeze the live product, as planned.
- Build a command-line audit script (4–5 days). It imports Vapi/Retell exports and tool-call logs, reads the calendar through the existing connectors, extracts the commitments and outputs a mismatch report.
- Test it on simulations, labelled as simulated.

**Until 8 Dec (Gate A, 25 calls):**
- Post real fixes in 2–3 booking threads a day: Vapi and Retell communities, the n8n forum, Skool AI Automation Society.
- DM agency owners found by snuepi-signals.
- On every call, ask:
  - their number of clients and which platforms;
  - the last time a wrong booking reached a client, and how they found out;
  - what it cost them;
  - what proof they send clients each month;
  - whether they have lost a client, and why;
  - what they pay for reliability tools today.
- Close every call by asking for a free 30-day audit on one client account.
- **Targets: 25 calls, ≥10 audits agreed, ≥5 delivered.**

**9 Dec–8 Jan (Gate B):**
- Ask every audit that showed a mismatch rate of ≥1% of booking calls, or any false "you're booked", for the paid pilot.
- **Gate B passes with ≥1 signed, priced pilot (target 3). Start the 6-week build only after the first signature.**
- Run one conversation in parallel with a white-label agency platform (Trillet or MyVoiceAIConnect type) about reselling.

## 5. Kill criteria (numeric, decided in advance)
1. Across ≥5 real audits, wrong commitments are under 0.5% of booking calls and no false "you're booked" is found. (Alternative threshold from another design: fewer than 1 per 200 booking calls in at least 3 of 8 audits.)
2. Fewer than 6 of 25 agencies grant read-only access for a free audit.
3. More than half of the agencies already run a DIY booking-token gate, and a native platform gate would cover more than 70% of the audit findings.
4. Zero signed, priced pilots by 8 Jan 2027, or every agency caps willingness to pay below €10 per client per month.
5. Vapi, Retell or GHL ships native post-call checking against the calendar before Gate B.

## 6. Biggest risks (honest)
- **This may be a builder's debugging problem, not a budget line.** No first-person evidence shows an agency losing a client over a wrong commitment.
- **The churn evidence comes from vendors.** "70–80% of churn is perception" and "dashboards reduce cancellations" are claims from Trillet and MyVoiceAIConnect, which sell those dashboards.
- **An observer catches errors only after the caller hung up.** If agencies want prevention, v1.5's live tool becomes v1.
- **The moat in year one is speed and channel, not technology.** Cekura, Roark or the platforms are one feature away from post-call reconciliation.

## 7. Path to scale
1. **2027:** agencies, bookings first, then prices and discounts. About 100 agencies × 15 clients ≈ €0.5M ARR.
2. **Chat, WhatsApp and email agents, plus refund and policy promises.** The EU angle: OLG Hamm (May 2026) holds the business liable for its chatbot's statements, and German IHKs (chambers of commerce) warn members about warning letters (Abmahnungen). Then marketplace listings and the live tool.
3. **Sell an OEM version** to vertical receptionist vendors, booking software and white-label agency platforms.
4. **The verified-outcome ledger becomes the data layer for AI liability insurers** (Armilla, Munich Re aiSure/Mosaic, AIUC-1, Testudo): underwriting scores, claims evidence, embedded cover. This is where snuepi's signed-record work pays off, and it is the venture-scale case.
