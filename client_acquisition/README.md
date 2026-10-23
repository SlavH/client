# Client Acquisition Module

Persistent CRM and proposal-drafting system for client acquisition.

## CRM CLI

```bash
python -m client_acquisition.scripts.crm stats          # Show CRM statistics
python -m client_acquisition.scripts.crm list --limit 50 # List leads
python -m client_acquisition.scripts.crm validate        # Validate JSONL records
python -m client_acquisition.scripts.crm export-report   # Export CRM report JSON
```

## Recurring batch

```bash
python -m client_acquisition.scripts.run_batch           # Full workflow
python -m client_acquisition.scripts.run_batch --leads-file path/to/leads.json  # With discovered leads
python -m client_acquisition.scripts.run_batch --no-sync              # Skip GitHub sync
```

## Data files

| File | Purpose |
|------|---------|
| `data/leads.jsonl` | Discovered and scored leads |
| `data/proposals.jsonl` | Draft proposals (one per lead) |
| `data/events.jsonl` | Execution history (append-only) |
| `data/suppression.jsonl` | Suppression list (opt-outs) |

## Lead scoring (0-100)

- Website/automation opportunity: 0-35
- Service fit (Full-Stack/web/AI): 0-25
- Evidence reliability: 0-20
- Target market relevance: 0-10
- Public contact route: 0-10

Proposals are drafted only for leads scoring >= 60 (configurable in `config.json`).

## Safety

- All proposals are `draft` status; `approved_for_sending` is `false`.
- No external-send functionality exists.
- Suppression overrides all scores and statuses.
- Never invent contact details; prefer official public contact pages.
