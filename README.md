# Client Acquisition System

Autonomous client acquisition system for a freelance Full-Stack developer based in Yerevan, Armenia.

## What this is

A research and proposal-drafting CRM that repeatedly discovers local businesses, verifies them,
scores them, drafts personalized proposals, and persists everything to this GitHub repository.

This is **not** an autonomous mass-messaging bot. It never sends emails, Telegram messages,
contact forms, or any external communication unless an explicit human triggers an approved send
through the Resend sender (see below). All proposals are drafts only by default.

## Repository structure

```
client_acquisition/
  README.md          # Module-level documentation
  AGENT_PROMPT.md    # Recurring research instructions + safety constraints
  config.json        # Target market, run limit, score threshold, email limits, data paths
  schemas/
    lead.schema.json
    proposal.schema.json
  data/
    leads.jsonl
    proposals.jsonl
    events.jsonl
    suppression.jsonl
    sends.jsonl      # Send intent / history (append-only; never secrets)
  scripts/
    crm.py           # CRM layer: stats / list / validate / export-report
    validate.py      # JSONL validation
    report.py        # Report generation
    run_batch.py     # One-command recurring workflow
    discovery.py     # Lead scoring + proposal generation
    git_sync.py      # Safe GitHub sync (commit + push, no --force)
    resend_sender.py # Resend email sender: check-config / send-test / send-approved
  templates/
    proposal.md
  reports/           # Generated reports (.gitkeep)
tests/
  test_crm.py
  test_deduplication.py
  test_safety.py
  test_resend_sender.py
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

## Resend email sender (approved sends only)

The sender is **dry-run by default**. A real submission requires the explicit `--send` flag.
No secrets are ever printed, committed, or written to project files.

Commands:
```bash
# 1. Validate configuration (never exposes secret values)
python -m client_acquisition.scripts.resend_sender check-config

# 2. Send one explicitly authorized test email (dry-run unless --send)
python -m client_acquisition.scripts.resend_sender send-test --to verified@example.com [--send]

# 3. Send an approved proposal draft (dry-run unless --send)
python -m client_acquisition.scripts.resend_sender send-approved --lead-key <KEY> --to <recipient> [--send]
```

Configuration is read from environment variables only (never hard-coded):
- `RESEND_API_KEY` — Resend API key
- `RESEND_FROM_EMAIL` — verified sender address

### Colab setup (notebook cells)

Install the official Resend Python SDK:

```python
!pip install -q resend
```

Configure secrets using Colab Secrets (left panel → lock icon → add `RESEND_API_KEY` and
`RESEND_FROM_EMAIL`), then expose them as environment variables for the notebook runtime:

```python
import os
from google.colab import userdata

# Pull from Colab Secrets (values are not printed)
os.environ["RESEND_API_KEY"] = userdata.get("RESEND_API_KEY")
os.environ["RESEND_FROM_EMAIL"] = userdata.get("RESEND_FROM_EMAIL")
```

Validate configuration without exposing the key:

```python
!python -m client_acquisition.scripts.resend_sender check-config
```

Run a dry-run test (no email is submitted; `--send` is omitted):

```python
!python -m client_acquisition.scripts.resend_sender send-test --to verified-test@example.com
```

Send one explicitly authorized test email (requires `--send` and a verified recipient):

```python
!python -m client_acquisition.scripts.resend_sender send-test --to verified-test@example.com --send
```

Resume after a Colab reconnect:

```python
!git -C /content/client pull --ff-only
!python -m client_acquisition.scripts.resend_sender check-config
!python -m client_acquisition.scripts.crm stats
```

CRM data lives in `client_acquisition/data/*.jsonl` and is restored from Git on reconnect.
The sender is idempotent: re-running does not create duplicate sends for the same message.

### Domain verification

Before real sends, verify your sending domain in Resend (Dashboard → Domains) and add the
required DNS records (SPF/DKIM). `RESEND_FROM_EMAIL` must use a verified domain or a verified
single sender address. `check-config` only validates that the env vars are present and that
`RESEND_FROM_EMAIL` is a syntactically valid email; it does not verify domain ownership.

### Status semantics

Resend API acceptance means `submitted`, **not** delivered. The sender records:
- `submitted` — Resend accepted the message.
- `send_status_unknown` — API response was uncertain (no message ID); investigate before retrying.
- `failed` — the provider rejected the submission.

Delivery (`delivered`) and bounce (`bounced`) statuses require Resend webhooks or polling the
Resend Email API by message ID; they are not polled by this tool. Never blindly resend an
uncertain message.

### Limits

- Default dry-run mode; real sends need `--send`.
- Configurable per-run limit (default 5) and daily limit (default 10) in `config.json` `email`.
- No bulk blasting, no automatic follow-up campaigns.
- Suppression list (`data/suppression.jsonl`) and existing send history are checked before every send.
- Stable idempotency key per message payload; the same key is never reused with a different payload.

## Safety

- No external-send methods exist in the CRM (`crm_has_no_send_methods` tested). Sending lives
  only in `resend_sender.py` and requires explicit human action.
- Proposals are `draft` only; `approved_for_sending` is `false` and is **not** a send trigger.
- `send-approved` requires proposal status `approved` (explicit human approval).
- Suppression list takes precedence over all scores/statuses.
- Atomic file writes + `fcntl` file locking prevent corruption.
- Malformed JSONL records are reported, never silently deleted.
- Never invent recipient addresses or business facts.
- Never contact suppressed or opted-out recipients.
- Prevent duplicate sends across runs via idempotency keys + send history.

## Running tests

```bash
python -m unittest discover -s tests -v
```

41 tests cover: domain normalization, duplicate detection, duplicate proposal prevention,
manual status preservation, suppression precedence, JSONL validation, atomic updates,
repeated execution, no external-send behavior, mocked Resend sends (never real email),
check-config secret handling, suppression/limits blocking, idempotency.

## GitHub sync

The system commits and pushes to the configured `origin` remote / `master` branch only.
It never uses `git push --force`. Tokens are never stored in tracked files.
