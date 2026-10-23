# Client Acquisition System

Autonomous client acquisition system for a freelance Full-Stack developer based in Yerevan, Armenia.

## What this is

A research and proposal-drafting CRM that repeatedly discovers local businesses, verifies them,
scores them, drafts personalized proposals, and persists everything to this GitHub repository.

This is **not** an autonomous mass-messaging bot. It never sends emails, Telegram messages,
contact forms, or any external communication. All proposals are drafts only; external contact
requires a separate human decision.

## Repository structure

```
client_acquisition/
  README.md          # Module-level documentation
  AGENT_PROMPT.md    # Recurring research instructions + safety constraints
  config.json        # Target market, run limit, score threshold, data paths
  schemas/
    lead.schema.json
    proposal.schema.json
  data/
    leads.jsonl
    proposals.jsonl
    events.jsonl
    suppression.jsonl
  scripts/
    crm.py           # CRM layer: stats / list / validate / export-report
    validate.py      # JSONL validation
    report.py        # Report generation
    run_batch.py     # One-command recurring workflow
    discovery.py     # Lead scoring + proposal generation
    git_sync.py      # Safe GitHub sync (commit + push, no --force)
  templates/
    proposal.md
  reports/           # Generated reports (.gitkeep)
tests/
  test_crm.py
  test_deduplication.py
  test_safety.py
AGENTS.md            # Operational instructions for OpenCode
README.md            # This file
```

## CRM commands

```bash
python -m client_acquisition.scripts.crm stats
python -m client_acquisition.scripts.crm list --limit 50
python -m client_acquisition.scripts.crm validate
python -m client_acquisition.scripts.crm export-report --out reports/myreport.json
```

## One-command recurring batch

```bash
python -m client_acquisition.scripts.run_batch
```

Optionally pass a discovered-leads JSON file (produced by manual web search):

```bash
python -m client_acquisition.scripts.run_batch --leads-file discovered_leads.json
```

Skip GitHub sync:

```bash
python -m client_acquisition.scripts.run_batch --no-sync
```

## Safety

- No external-send methods exist in the CRM (`crm_has_no_send_methods` tested).
- Proposals are `draft` only; `approved_for_sending` is `false` and is **not** a send trigger.
- Suppression list takes precedence over all scores/statuses.
- Atomic file writes + `fcntl` file locking prevent corruption.
- Malformed JSONL records are reported, never silently deleted.

## Running tests

```bash
python -m unittest discover -s tests -v
```

## GitHub sync

The system commits and pushes to the configured `origin` remote / `master` branch only.
It never uses `git push --force`. Tokens are never stored in tracked files.
