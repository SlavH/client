# Recurring Research Instructions and Safety Constraints

Use this prompt on every research run. Do not deviate.

## Objective

Discover real businesses in Armenia (priority: Yerevan) that may benefit from web/Full-Stack/
AI automation services. Verify, deduplicate, score, and draft personalized proposals. Never
send any external communication.

## Safety constraints (absolute)

1. **Never send** emails, Telegram messages, DMs, contact forms, or any external message.
2. **Never submit** forms on external websites.
3. **Never make purchases, create accounts, or spend money.**
4. **Never publish** generated work publicly.
5. **Never contact** a business merely because its score is high.
6. **Never auto-follow up.**
7. `approved_for_sending = false` is **not** permission to send. All proposals are `draft`.
8. Suppression list (`data/suppression.jsonl`) overrides every score, status, or flag.

## Discovery rules

- Target: Armenia first, Yerevan priority (configurable in `config.json`).
- Max businesses per run: 10 (configurable, never exceeded).
- Use web search and browser tools. Inspect official websites and reliable public sources.
- Do **not** invent technical problems, owners, budgets, revenues, emails, or contacts.
- Record uncertainty explicitly.
- Do not assume every business needs a website.

## Lead record (required fields)

- `lead_key` — stable unique key (normalized domain, or name+location fallback)
- `business_name`, `city`, `country`
- `website_url` (if available), `normalized_domain`
- `business_category`, `public_source_urls`
- `discovered_at`, `last_verified_at`
- `evidence_observations` (evidence-backed only)
- `proposed_opportunity`
- `fit_score` (0-100) + `score_explanation` (explicit per-component)
- `public_contact_page` (if available)
- `status`, `follow_up_eligible`, `research_notes`, `suppressed`

## Scoring (0-100, every component needs an explanation)

1. Website/automation opportunity: 0-35
2. Fit with Full-Stack/web/AI automation: 0-25
3. Evidence reliability/specificity: 0-20
4. Target market relevance: 0-10
5. Public contact route: 0-10

Missing evidence lowers confidence — never treat it as proof of a problem.
Proposals drafted only for score >= 60 (configable threshold).

## Proposal draft rules

- Refer to **one specific, verified observation**.
- Suggest **one realistic improvement**.
- Explain benefit **without promising unsupported results**.
- No generic mass-marketing language.
- No pretending a demo/audit/implementation exists.
- Language: Armenian / Russian / English (pick based on business context).
- Include a subject line.
- Record `facts_used` for personalization.
- Never invent contact info. Prefer official public contact pages.
- Status: `draft` initially.

## Deduplication

- Normalize domains: remove scheme, www., paths, fragments, trailing slashes.
- Primary key: normalized domain. Fallback: normalized name + location.
- Never create duplicate leads or proposals for an existing `lead_key`.
- Record why duplicates were skipped.

## Persistence

- CRM data in `client_acquisition/data/*.jsonl` (atomic writes, fcntl file locking).
- Malformed JSONL records are reported, never silently deleted.
- Re-running is idempotent; existing statuses/notes/timestamps are preserved.
- Human edits are never overwritten by generated content.

## GitHub sync

- Check branch and status before committing.
- Stage only `client_acquisition/`, `tests/`, `AGENTS.md`, `README.md`.
- Descriptive commits, push to `origin`/`master` only, never `--force`.
- Never store tokens in tracked files.
- Report sync failures clearly; never discard local results.

## Output

Report results and blockers. If web/GitHub/network is unavailable, preserve data and
explain what could not be completed. Never fabricate successful execution.
