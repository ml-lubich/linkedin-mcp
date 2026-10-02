# Joe referral flow (LinkedIn)

Policy lives in the linkedin-outreach skill; this is the mechanical part. Agents write message bodies only, never code.

1. `linkedin login` (once; session in the already-open Chrome).
2. `linkedin scan --json > cands.json`. Candidates already pass the rules: we did not speak last, referee not mentioned, not excluded (Mach, Anduril, EchoStar/Dish, AMD, W3Sourcing, Perry Barrow), no one at that company in the shared ledger `~/.config/joe-referral/ledger.json`. Each has a `fit` of `strong`, `stretch` or `skip`.
3. Sort each candidate: real job, sales, or Misha's own. Drop `skip` fits (5+ years, senior/staff/lead, clearance, C++/Rust/Go/.NET/Salesforce-only, QA/SDET/RPA). Mention `stretch` honestly or leave it.
4. Write one personalized body (3-5 sentences) per job into a queue file `q.json`: `[{"name", "url", "company", "role", "body"}]`.
5. `linkedin referral queue q.json --confirm`. It sends, then appends to the ledger so a re-run never double-sends.

Never edit the ledger by hand; malformed JSON makes every tool fail loudly on purpose.
