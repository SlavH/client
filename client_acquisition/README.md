# Client Acquisition Module

Persistent CRM and proposal-drafting system for client acquisition, plus an optional Resend
email sender for approved proposals (dry-run by default).

## CRM CLI

```bash
python -m client_acquisition.scripts.crm stats          # Show CRM statistics
python -m client_acquisition.scripts.crm list --limit 50 # List leads
python -m client_acquisition.scripts.crm validate        # Validate JSONL records
python -m client_acquisition.scripts.crm export-report   # Export CRM report JSON
```

## Resend email sender CLI

Dry-run by default. Real submission requires the explicit `--send` flag.
Secrets are read only from environment variables (`RESEND_API_KEY`, `RESEND_FROM_EMAIL`)
and are never printed or stored.

```bash
python -m client_acquisition.scripts.resend_sender check-config
python -m client_acquisition.scripts.resend_sender send-test --to verified@example.com [--send]
python -m client_acquisition.scripts.resend_sender send-approved --lead-key <KEY> --to <recipient> [--send]
```

## Recurring batch

```bash
python -m client_acquisition.scripts.run_batch           # Full workflow
python -m client_acquisition.scripts.run_batch --leads-file path/to/leads.json
python -m client_acquisition.scripts.run_batch --no-sync
```

## Data files

| File | Purpose |
|------|---------|
| `data/leads.jsonl` | Discovered and scored leads |
| `data/proposals.jsonl` | Draft/approved proposals (one per lead) |
| `data/events.jsonl` | Execution history (append-only) |
| `data/suppression.jsonl` | Suppression list (opt-outs) |
| `data/sends.jsonl` | Send intent / history (append-only) |

## Lead scoring (0-100)

- Website/automation opportunity: 0-35
- Service fit (Full-Stack/web/AI): 0-25
- Evidence reliability: 0-20
- Target market relevance: 0-10
- Public contact route: 0-10

Proposals are drafted only for leads scoring >= 60 (configurable in `config.json`).

## Safety

- All proposals are `draft` status; `approved_for_sending` is `false`.
- `send-approved` requires proposal status `approved`.
- No external-send methods exist in the CRM.
- Suppression overrides all scores and statuses.
- Never invent contact details; prefer official public contact pages.
- Idempotency keys prevent duplicate sends across runs.
