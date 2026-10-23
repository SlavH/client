# Operational Instructions for OpenCode (SlavH/client)

## Purpose

This repository hosts a client acquisition system for a freelance Full-Stack developer in Yerevan, Armenia.
It discovers businesses, scores them, drafts personalized proposals, and persists everything to GitHub.

## One command to run a research batch

```bash
python -m client_acquisition.scripts.run_batch
```

If you have manually discovered leads (via web search), save them as JSON and pass the file:

```bash
python -m client_acquisition.scripts.run_batch --leads-file discovered_leads.json
```

## What the batch does (in order)

1. Inspects Git status and existing CRM state.
2. Synchronizes safely with `origin` / `master` (fetch + fast-forward merge; no `--force`).
3. Validates all JSONL records.
4. Processes discovered leads: deduplicate, score (0-100), draft proposals for score >= 60.
5. Saves and validates results (atomic writes).
6. Generates a report in `client_acquisition/reports/`.
7. Commits and pushes only `client_acquisition/`, `tests/`, `AGENTS.md`, `README.md`.

## Resuming after a disconnect / new session

1. `git pull` (or let `run_batch` sync) to restore repository state.
2. CRM data lives in `client_acquisition/data/*.jsonl` — it survives across sessions via Git.
3. Run `python -m client_acquisition.scripts.run_batch` to continue from persisted state.
4. The CRM is idempotent: re-running does not create duplicates.

## Configure

Edit `client_acquisition/config.json`:

- `target_market.country` / `.city` — default Armenia / Yerevan
- `discovery.max_businesses_per_run` — default 10 (never exceeded)
- `scoring.proposal_threshold` — default 60

## Safety (read carefully)

- This system **never** sends emails, Telegram messages, DMs, or contact forms.
- `approved_for_sending = false` is **not** a send trigger; it is a draft flag.
- External communication requires a separate, explicit human decision.
- Suppression list (`data/suppression.jsonl`) overrides all scores and statuses.

## CRM commands

```bash
python -m client_acquisition.scripts.crm stats
python -m client_acquisition.scripts.crm list --limit 50
python -m client_acquisition.scripts.crm validate
python -m client_acquisition.scripts.crm export-report
```

## Gmail API email sender commands (dry-run by default; `--send` for real submission)

```bash
python -m client_acquisition.scripts.gmail_sender check-config
python -m client_acquisition.scripts.gmail_sender send-test --to <verified@gmail.com> [--send]
python -m client_acquisition.scripts.gmail_sender send-approved --lead-key <KEY> --to <recipient> [--send]
```

Never print or commit `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` / `GMAIL_FROM_EMAIL`. Read them from environment only.

**Proposal approval:** proposals are auto-approved (status `approved`) when created. Real sends still require explicit human authorization: the `--send` flag on `send-approved` or `send-test`. `approved_for_sending=false` is **not** a send trigger — no email is sent without `--send`.

## Tests

```bash
python -m unittest discover -s tests -v
```

39 tests cover: domain normalization, duplicate detection, duplicate proposal prevention,
manual status preservation, suppression precedence, JSONL validation, atomic updates,
repeated execution, no external-send behavior, mocked Gmail sends (never real email),
check-config secret handling, suppression/limits blocking, idempotency.

## /task and /tasklist (grinev/opencode-telegram)

If the Telegram bot integration is present (`/content/opencode-telegram-bot`), use `/task` to
create a one-off research task and `/tasklist` to view pending tasks.

- Do **not** create recurring/scheduled tasks automatically during setup.
- The bot interface does not expose a reliable task-ID deduplication mechanism, so avoid
  creating duplicate `/task` entries manually. Check `/tasklist` first before creating.
- If unsure, create the task manually via the bot and record its ID in `client_acquisition/data/events.jsonl`.

## Files safe to commit

`client_acquisition/`, `tests/`, `AGENTS.md`, `README.md`, `.gitignore`.

CRM JSONL data contains public business information only. No secrets, tokens, cookies, or
personal contact details are committed. If you need private CRM data, use a private repo or
an external data directory via `config.json` `data.external_directory`.
