export const meta = {
  name: 'agentic-transition-problem-radar',
  description: 'Hunt first-person complaints about agentic-transition problems across channels, cluster, adversarially verify, score',
  phases: [
    { title: 'Hunt', detail: 'segment x channel hunters collect first-person problem mentions with quotes + URLs' },
    { title: 'Cluster', detail: 'merge raw mentions into distinct problem themes' },
    { title: 'Verify', detail: 'per theme: verify quotes, map existing solutions, score opportunity' },
    { title: 'Gaps', detail: 'completeness critic finds missed segments' },
  ],
}

const TODAY = (args && args.today) || 'today'
const MENTION = {
  type: 'object',
  properties: {
    mentions: { type: 'array', items: { type: 'object', properties: {
      problem: { type: 'string', description: 'one-sentence problem statement in plain words' },
      quote: { type: 'string', description: 'verbatim or near-verbatim text from the person' },
      url: { type: 'string' },
      channel: { type: 'string', description: 'reddit, hackernews, x, github, linkedin, forum, blog, stackoverflow, discord, other' },
      author_role: { type: 'string', description: 'who is speaking: e.g. staff engineer at fintech, solo founder, IT admin' },
      date: { type: 'string', description: 'YYYY-MM or best guess, empty if unknown' },
      segment: { type: 'string' },
      intensity: { type: 'integer', description: '1-5 how painful, based on language' },
      wtp_signal: { type: 'string', description: 'evidence they would pay / already pay / budget, or empty' },
      workaround: { type: 'string', description: 'what they do today, or empty' },
    }, required: ['problem','quote','url','channel','author_role','date','segment','intensity','wtp_signal','workaround'] } },
  },
  required: ['mentions'],
}

const BASE = `You are a hedge-fund research analyst hunting for UNSOLVED PROBLEMS created by the "agentic transition" (the shift from humans using software to AI agents doing work: coding agents, browser/computer-use agents, enterprise agent deployments, agent-to-agent commerce, MCP/tool ecosystems, autonomous workflows). Today is ${TODAY}; prioritise the last 12 months, most recent first.
Source PRIMARILY from real people describing their own problems: Reddit threads, Hacker News comments, X/Twitter posts, GitHub issues/discussions, LinkedIn posts, Stack Overflow, community forums (Discourse, Cursor/LangChain/n8n/OpenAI/Anthropic forums), dev.to/Substack posts by practitioners. Vendor marketing and analyst reports do NOT count as mentions (you may use them only to find threads).
Use WebSearch heavily (run at least 15 distinct searches with complaint language: "struggling with", "anyone else", "is there a tool", "nightmare", "I wish", "we gave up", "how do you handle", "broke production", "cost us"), and WebFetch to open threads and copy real quotes. Never invent quotes or URLs; if you cannot open a page, paraphrase from the search snippet and say so in the quote field ("[snippet]").
Return 12-25 mentions, each a distinct problem or a distinct person confirming a problem.`

const HUNTERS = [
  ['coding-agents', 'Developers using coding agents (Claude Code, Cursor, Codex, Copilot agent, Devin): review burden, context limits, cost blowups, broken code in prod, multi-agent coordination, CI/test pain, monorepo, code ownership.'],
  ['agent-builders', 'Engineers building agents/agentic products: evals, reliability, non-determinism, observability/tracing, debugging long runs, memory, state, orchestration frameworks, tool-calling failures, prompt regressions across model upgrades.'],
  ['mcp-tools', 'MCP servers and tool ecosystems: auth/OAuth for agents, tool sprawl, security of MCP servers, prompt injection via tools, versioning, discovery, rate limits, enterprise gateways.'],
  ['security-identity', 'Security, identity and access for agents: agent identity, delegated credentials, secrets, least privilege, prompt injection incidents, data exfiltration, audit logs, non-human identity, CISOs blocking agents.'],
  ['enterprise-deploy', 'Enterprise IT / ops leaders deploying agents: pilot-to-production gap, ROI proof, governance, change management, integration with legacy systems (SAP, Salesforce, ServiceNow), procurement, shadow AI, agent sprawl.'],
  ['browser-web', 'Browser/computer-use agents and the web: sites blocking bots, CAPTCHAs, Cloudflare, websites not agent-readable, scraping legality, agents failing on UIs, publishers losing traffic to agents, SEO-to-AI-visibility shift.'],
  ['agent-commerce', 'Agent payments and commerce: agents buying things, payments/cards for agents, fraud, merchant acceptance of agent traffic, checkout, refunds, liability, KYC for agents, B2B procurement by agents.'],
  ['smb-operators', 'Small business owners and operators adopting agents: setup complexity, trust, wrong actions (emails, bookings), integration with their tools, cost, AI receptionists/voice agents failing, customers dealing with businesses via agents.'],
  ['knowledge-work', 'Knowledge workers and functions (support, sales, marketing, finance, legal, recruiting): agents producing slop, verification burden, hallucinated outputs, job redesign, managing a team of agents, AI SDR spam, inbox flooded by agent-generated outreach, hiring fraud via AI.'],
  ['infra-cost', 'Infra, cost and compute for agents: token bills exploding, rate limits, latency, GPU/inference capacity, caching, cost attribution per agent/user, pricing models (seat vs outcome), FinOps for AI.'],
  ['data-context', 'Data and context for agents: RAG quality, stale knowledge, permissions-aware retrieval, connecting internal data, documentation for agents (llms.txt), APIs not designed for agents, data quality, knowledge capture.'],
  ['regulated-liability', 'Regulated industries and liability: healthcare, finance, insurance, legal using agents; compliance (EU AI Act, SOC2), accountability for agent errors, human-in-the-loop requirements, insurance for AI agents, audit trails.'],
  ['human-labor', 'People affected by the transition: junior devs and workers displaced or reskilling, freelancers competing with agents, managers evaluating AI-augmented employees, education/training gaps, contractors cleaning up AI-generated messes (vibe-coding cleanup).'],
  ['agent-to-agent', 'Multi-agent and agent-to-agent interaction: protocols (A2A, MCP), agents negotiating with agents, spam/abuse by agents, trust/reputation between agents, coordination failures, agents talking to customer-service bots.'],
]

phase('Hunt')
const hunts = await parallel(HUNTERS.map(([key, focus]) => () =>
  agent(`${BASE}\n\nYOUR SEGMENT: ${key}. ${focus}`, { label: `hunt:${key}`, phase: 'Hunt', schema: MENTION })
    .then(r => r ? r.mentions.map(m => ({ ...m, hunter: key })) : [])))
const all = hunts.filter(Boolean).flat()
log(`${all.length} raw mentions collected`)

phase('Cluster')
const CLUSTERS = {
  type: 'object',
  properties: { themes: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' }, title: { type: 'string' }, problem: { type: 'string' },
    who_has_it: { type: 'string' }, mention_indexes: { type: 'array', items: { type: 'integer' } },
  }, required: ['id','title','problem','who_has_it','mention_indexes'] } } },
  required: ['themes'],
}
const numbered = all.map((m, i) => `[${i}] (${m.channel}, ${m.date}, ${m.author_role}) ${m.problem} :: "${m.quote.slice(0, 300)}"`).join('\n')
const clustered = await agent(`Cluster these ${all.length} first-person problem mentions about the agentic transition into 20-35 DISTINCT, specific, solvable problem themes (not vague categories like "reliability"; prefer "No way to replay and diff a failed 2-hour agent run"). Every mention index must be assigned to exactly one theme; themes with a single weak mention may be merged. Use short kebab-case ids.\n\n${numbered}`,
  { label: 'cluster', phase: 'Cluster', schema: CLUSTERS })
const themes = clustered ? clustered.themes : []
log(`${themes.length} themes`)

const VERDICT = {
  type: 'object',
  properties: {
    real: { type: 'boolean', description: 'false if quotes are fabricated/unverifiable, problem is already well solved, or it is vendor hype not user pain' },
    verified_urls: { type: 'array', items: { type: 'string' } },
    extra_evidence: { type: 'array', items: { type: 'object', properties: { quote: { type: 'string' }, url: { type: 'string' }, date: { type: 'string' } }, required: ['quote','url','date'] } },
    existing_solutions: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, what: { type: 'string' }, gap: { type: 'string' } }, required: ['name','what','gap'] } },
    scores: { type: 'object', properties: {
      pain: { type: 'integer' }, frequency: { type: 'integer' }, willingness_to_pay: { type: 'integer' },
      momentum: { type: 'integer' }, solution_gap: { type: 'integer' }, market_size: { type: 'integer' },
    }, required: ['pain','frequency','willingness_to_pay','momentum','solution_gap','market_size'] },
    why_now: { type: 'string' },
    who_pays: { type: 'string' },
    opportunity: { type: 'string', description: 'the product/company that would solve it, one or two sentences' },
    investable_angle: { type: 'string', description: 'public/private companies exposed (beneficiaries or losers), tickers where relevant' },
    skeptic_note: { type: 'string', description: 'strongest reason this might not be a good opportunity' },
  },
  required: ['real','verified_urls','extra_evidence','existing_solutions','scores','why_now','who_pays','opportunity','investable_angle','skeptic_note'],
}

phase('Verify')
const verified = await parallel(themes.map(t => () => {
  const ev = t.mention_indexes.map(i => all[i]).filter(Boolean)
  const evText = ev.map(m => `- ${m.channel} ${m.date} ${m.author_role}: "${m.quote}" ${m.url}`).join('\n')
  return agent(`You are a skeptical diligence analyst. Today is ${TODAY}. Theme: "${t.title}" — ${t.problem} (affects: ${t.who_has_it}).\nEvidence gathered by another analyst:\n${evText}\n\nTasks: (1) WebFetch/WebSearch to check at least 3 of the URLs really exist and say roughly what is quoted; list the confirmed ones in verified_urls. (2) Find 2-5 MORE first-person mentions (forums, Reddit, HN, X, GitHub) from the last 12 months. (3) Search for existing products/open-source tools that solve this and state their gap. (4) Score 1-5 each: pain, frequency, willingness_to_pay, momentum (is it growing), solution_gap (5 = nobody solves it well), market_size. (5) Try to REFUTE: set real=false if evidence is fabricated, is vendor marketing rather than user pain, or the problem is already well solved. Be concrete and terse.`,
    { label: `verify:${t.id}`, phase: 'Verify', schema: VERDICT }).then(v => v ? ({ ...t, evidence: ev, verdict: v }) : null)
}))

phase('Gaps')
const GAPS = { type: 'object', properties: { missing: { type: 'array', items: { type: 'object', properties: {
  title: { type: 'string' }, problem: { type: 'string' }, quote: { type: 'string' }, url: { type: 'string' }, date: { type: 'string' }, why_missed: { type: 'string' },
}, required: ['title','problem','quote','url','date','why_missed'] } } }, required: ['missing'] }
const gaps = await agent(`${BASE}\n\nCOMPLETENESS CRITIC. These themes were already found:\n${themes.map(t => '- ' + t.title).join('\n')}\n\nFind 6-12 important agentic-transition problems NOT covered above (other industries, geographies, non-English communities, hardware/robotics agents, government, education, creators, gaming, real estate, logistics). Each needs a real first-person quote + URL.`,
  { label: 'gaps', phase: 'Gaps', schema: GAPS })

return { today: TODAY, raw_mentions: all.length, themes: verified.filter(Boolean), gaps: gaps ? gaps.missing : [] }
