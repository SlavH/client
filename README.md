# Client Acquisition System

Autonomous client acquisition system for a freelance Full-Stack developer based in Yerevan, Armenia.

## What this is

A research and proposal-drafting CRM that repeatedly discovers local businesses, verifies them,
scores them, drafts personalized proposals, and persists everything to this GitHub repository.

This is **not** an autonomous mass-messaging bot. It never sends emails, Telegram messages,
contact forms, or any external communication unless an explicit human triggers an approved send
through the Gmail API sender (see below). Proposals are auto-approved (status `approved`) when
created, but no email is sent without the explicit `--send` flag.

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
    gmail_sender.py  # Gmail API email sender: check-config / send-test / send-approved
  templates/
    proposal.md
  reports/           # Generated reports (.gitkeep)
tests/
  test_crm.py
  test_deduplication.py
  test_safety.py
  test_gmail_sender.py
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

## Gmail API email sender (approved sends only)

The sender is **dry-run by default**. A real submission requires the explicit `--send` flag.
No secrets are ever printed, committed, or written to project files.

Commands:
```bash
# 1. Validate configuration (never exposes secret values)
python -m client_acquisition.scripts.gmail_sender check-config

# 2. Send one explicitly authorized test email (dry-run unless --send)
python -m client_acquisition.scripts.gmail_sender send-test --to verified@gmail.com [--send]

# 3. Send an approved proposal draft (dry-run unless --send)
python -m client_acquisition.scripts.gmail_sender send-approved --lead-key <KEY> --to <recipient> [--send]
```

Configuration is read from environment variables only (never hard-coded):
- `GMAIL_CLIENT_ID` — OAuth2 client ID
- `GMAIL_CLIENT_SECRET` — OAuth2 client secret
- `GMAIL_REFRESH_TOKEN` — OAuth2 refresh token (long-lived)
- `GMAIL_FROM_EMAIL` — sender address (your Gmail or verified alias)

### Colab setup (notebook cells)

Install the Google API client libraries:

```python
!pip install -q google-api-python-client google-auth-oauthlib google-auth
```

Configure secrets using Colab Secrets (left panel → lock icon → add
`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_FROM_EMAIL`), then
expose them as environment variables for the notebook runtime:

```python
import os
from google.colab import userdata

# Pull from Colab Secrets (values are not printed)
os.environ["GMAIL_CLIENT_ID"] = userdata.get("GMAIL_CLIENT_ID")
os.environ["GMAIL_CLIENT_SECRET"] = userdata.get("GMAIL_CLIENT_SECRET")
os.environ["GMAIL_REFRESH_TOKEN"] = userdata.get("GMAIL_REFRESH_TOKEN")
os.environ["GMAIL_FROM_EMAIL"] = userdata.get("GMAIL_FROM_EMAIL")
```

Before real sending, complete the OAuth flow once (Desktop app) to obtain a refresh token and
store it in `GMAIL_REFRESH_TOKEN`.

Validate configuration without exposing secrets:

```python
!python -m client_acquisition.scripts.gmail_sender check-config
```

Run a dry-run test (no email is submitted; `--send` is omitted):

```python
!python -m client_acquisition.scripts.gmail_sender send-test --to verified-test@gmail.com
```

Send one explicitly authorized test email (requires `--send` and a verified recipient):

```python
!python -m client_acquisition.scripts.gmail_sender send-test --to verified-test@gmail.com --send
```

Resume after a Colab reconnect:

```python
!git -C /content/client pull --ff-only
!python -m client_acquisition.scripts.gmail_sender check-config
!python -m client_acquisition.scripts.crm stats
```

CRM data lives in `client_acquisition/data/*.jsonl` and is restored from Git on reconnect.
The sender is idempotent: re-running does not create duplicate sends for the same message.

### Sending from Gmail

`GMAIL_FROM_EMAIL` must be the Gmail account that owns the OAuth credentials (or an alias
configured in that Gmail account). There is no separate domain verification step like Resend;
Google handles sender identity through the OAuth account.

### Status semantics

Gmail API acceptance means `submitted`, **not** delivered. The sender records:
- `submitted` — Gmail accepted the message.
- `send_status_unknown` — API response was uncertain (no message ID); investigate before retrying.
- `failed` — the provider rejected the submission.

Delivery (`delivered`) and bounce (`bounced`) statuses are not polled by this tool. Never
blindly resend an uncertain message.

### Limits

- Default dry-run mode; real sends need `--send`.
- Configurable per-run limit (default 5) and daily limit (default 10) in `config.json` `gmail`.
- No bulk blasting, no automatic follow-up campaigns.
- Suppression list (`data/suppression.jsonl`) and existing send history are checked before every send.
- Stable idempotency key per message payload; the same key is never reused with a different payload.

## Safety

- No external-send methods exist in the CRM (`crm_has_no_send_methods` tested). Sending lives
  only in `gmail_sender.py` and requires explicit human action.
- Proposals are `draft` only; `approved_for_sending` is `false` and is **not** a send trigger.
**Proposal approval:** proposals are auto-approved (status `approved`) when created. Real sends
still require explicit human authorization: the `--send` flag on `send-approved` or `send-test`.
`approved_for_sending=false` is **not** a send trigger — no email is sent without `--send`.
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

55 tests cover: domain normalization, duplicate detection, duplicate proposal prevention,
manual status preservation, suppression precedence, JSONL validation, atomic updates,
repeated execution, no external-send behavior, mocked Gmail sends (never real email),
check-config secret handling, suppression/limits blocking, idempotency.

## GitHub sync

The system commits and pushes to the configured `origin` remote / `master` branch only.
It never uses `git push --force`. Tokens are never stored in tracked files.
