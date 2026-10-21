# Joe referral flow (LinkedIn)

Policy lives in the `linkedin-outreach` skill. This file is the repeatable execution procedure for a candidate referral campaign. Use the user's existing signed-in Chrome session; never launch another browser to work around a disconnected automation endpoint.

## Prepare the campaign

1. Read the candidate's current resume and portfolio before drafting. Use only claims supported there. For Joe, grounded highlights include building Briopedia from 0 to 1; combining BM25, vector retrieval, and a Kuzu knowledge graph; a 100-case evaluation set scoring 96% groundedness; Salesforce triage with human review; and a data platform over 100k+ invoices that reduced reconciliation time by 70%. Do not inflate these into unsupported hours saved, universal 100% grounding, or claims that every target is hiring.
2. Inspect the candidate-level ledger at `~/.config/joe-referral/ledger.json` and the current conversation history. Deduplicate by person and company, not only by exact name. Respect the exclusions in the source policy (Mach, Anduril, EchoStar/Dish, AMD, W3Sourcing, Perry Barrow).
3. Rank the saved prospects by role fit and visible hiring evidence. Separate confirmed openings from speculative founder referrals. Use a concise, conversational referral note tailored to the recipient's product area; avoid generic praise and tool laundry lists.
4. Keep a campaign checkpoint outside the shared skill repository, for example `~/.config/joe-referral/campaign.json`. Track recipient, company, role, profile/thread URL, route, draft, status (`queued`, `sent`, `skipped`, `blocked`), timestamp, and reason. Never store private names, message bodies, or campaign data in this shared skill repo.

## Send safely and efficiently

1. Prefer the LinkedIn MCP/CLI workflow when attached to the active Chrome session. If it cannot reach the user's current browser, use the installed desktop browser driver against that existing Chrome window; do not start a second Chrome. Read the relevant browser-driver skill first.
2. For each prospect, inspect the profile/list row, relationship degree, message history, and available action. Route first-degree contacts to free DMs. For second-degree contacts, check whether LinkedIn offers a free Open Profile/InMail path before choosing a paid InMail. Never infer the route or credit cost from a prior lead.
3. Before every send, confirm the recipient identity, no prior campaign contact, the complete message, and any credit cost presented by LinkedIn. Spend a paid credit only for a strong-fit prospect when the user has authorized credit use. Do not attach a resume unless the UI supports the intended attachment and the right file is selected; otherwise include the portfolio/resume link and record `resume_delivery: portfolio_link`.
4. Send one message at a time. Verify it appears in the recipient's conversation as sent before updating the ledger/checkpoint. If the interface result is ambiguous, stop and inspect the conversation; never mark a draft or attempted click as sent.
5. Record a successful send immediately with recipient, company, role if known, timestamp, route (`first_degree_dm`, `open_profile_inmail`, or `paid_inmail`), thread/profile URL, resume variant/hash, and delivery mode. Keep message bodies in the private campaign checkpoint only if needed for audit; never put candidate contact details in this repository.
6. Work in bounded batches, then reconcile the checkpoint against LinkedIn's sent messages and the ledger. Pause on rate limits, warnings, uncertain recipients, or unexpected credit prompts. Do not send a bulk template to all saved leads.

## Queue-based automation

When the LinkedIn referral queue command is available, use its candidate filters and per-recipient review. Queue format: `[{"name", "url", "company", "role", "body"}]`. Review the rendered queue before invoking `linkedin referral queue ... --confirm`; confirm only contacts and message bodies that the user authorized. The queue command must deduplicate against thread history and the shared ledger, and append only verified sends.

Never edit the ledger by hand when a supported ledger command exists. Use the campaign tool's append/record operation, validate the JSON afterward, and retain an audit trail of skipped/blocked prospects as well as confirmed sends.
