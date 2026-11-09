export const meta = {
  name: 'market-gap-mapper',
  description: 'For each problem theme, map existing solutions + user complaints about them, then adversarially hunt for a solution that already closes the gap',
  phases: [
    { title: 'Map', detail: 'solution landscape, coverage ratings, complaints about solutions, absorption risk' },
    { title: 'Counter', detail: 'skeptic tries to find a solution that already covers the problem' },
  ],
}
const FILE = args.file
const N = args.n
const TODAY = args.today

const SOL = { type: 'object', properties: {
  name: { type: 'string' }, url: { type: 'string' },
  kind: { type: 'string', description: 'startup | open-source | incumbent-product | platform-native-feature' },
  coverage: { type: 'integer', description: '0-5: how fully it solves THIS exact problem for THIS buyer (5 = fully, shipped, GA)' },
  maturity: { type: 'integer', description: '1-5: 1 = waitlist/demo, 3 = GA with customers, 5 = category leader' },
  adoption_signal: { type: 'string', description: 'customers, stars, funding, ARR, or empty' },
  pricing: { type: 'string' },
  weaknesses: { type: 'string', description: 'what it misses for this problem' },
  user_complaints: { type: 'array', items: { type: 'object', properties: {
    quote: { type: 'string' }, url: { type: 'string' }, date: { type: 'string' } }, required: ['quote','url','date'] },
    description: 'first-person complaints by USERS of this solution (Reddit, HN, G2, GitHub issues, X). Empty if none found' },
}, required: ['name','url','kind','coverage','maturity','adoption_signal','pricing','weaknesses','user_complaints'] }

const MAP = { type: 'object', properties: {
  solutions: { type: 'array', items: SOL },
  absorption_risk: { type: 'integer', description: '1-5: likelihood a platform (OpenAI, Anthropic, Microsoft, Google, AWS, Okta, GitHub, Salesforce...) ships this free/bundled within 12 months' },
  absorption_note: { type: 'string' },
  whitespace: { type: 'string', description: 'the specific uncovered slice of the problem no solution handles; empty if none' },
  wedge: { type: 'string', description: 'the narrowest product a new entrant could ship to own that whitespace' },
}, required: ['solutions','absorption_risk','absorption_note','whitespace','wedge'] }

const COUNTER = { type: 'object', properties: {
  strongest_solution: { type: 'string' },
  url: { type: 'string' },
  coverage: { type: 'integer', description: '0-5 coverage of the exact problem by the strongest solution you found' },
  gap_holds: { type: 'boolean', description: 'true if no existing solution covers the problem at >=4 for the stated buyer' },
  reason: { type: 'string' },
  missed_solutions: { type: 'array', items: { type: 'string' }, description: 'relevant solutions the mapper did not list' },
}, required: ['strongest_solution','url','coverage','gap_holds','reason','missed_solutions'] }

const items = Array.from({ length: N }, (_, i) => i)
const res = await pipeline(items,
  i => agent(`Today is ${TODAY}. Read the JSON array in ${FILE} and take element index ${i} (a problem theme sourced from first-person complaints about the agentic transition).
Map the CURRENT SOLUTION LANDSCAPE for that exact problem as a buy-side analyst:
1. List 4-10 solutions: startups, open-source projects, incumbent products, and platform-native features (the field "known" lists ones already found; verify and extend). Use WebSearch (max 4 searches; search snippets are acceptable evidence, WebFetch is often blocked).
2. Rate each solution's coverage (0-5) of THIS problem for THIS buyer, and maturity (1-5). Be strict: a feature on a roadmap or a generic tool that could be configured to help is coverage <=2.
3. For the 1-3 most relevant solutions, record first-person complaints by their users if you find any (search "<name> problems", "<name> reddit", "<name> alternative").
4. Rate absorption_risk and state the whitespace (uncovered slice) and the narrowest wedge product. Never invent URLs.`,
    { label: `map:${i}`, phase: 'Map', schema: MAP }),
  (m, i) => m ? agent(`Today is ${TODAY}. Read element index ${i} of ${FILE}. A colleague claims this whitespace is unsolved: "${m.whitespace}". Solutions they found: ${m.solutions.map(s => `${s.name} (coverage ${s.coverage})`).join(', ')}.
Your job is to REFUTE the gap: find the single strongest existing product, OSS project, or platform feature that already solves this exact problem for this buyer (max 2 WebSearch calls). Set gap_holds=false if anything covers it at >=4. Default to skepticism.`,
    { label: `counter:${i}`, phase: 'Counter', schema: COUNTER }).then(c => ({ index: i, map: m, counter: c })) : null)
return res.filter(Boolean)
