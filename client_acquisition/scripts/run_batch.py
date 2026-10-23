"""One-command recurring workflow for the client acquisition system.

Usage:
    python -m client_acquisition.scripts.run_batch [--leads-file PATH] [--no-sync]

Steps:
  1. Inspect Git status and existing CRM state
  2. Synchronize safely with the configured remote when possible
  3. Validate existing records
  4. Process discovered leads (dedup, score, proposal drafts)
  5. Save and validate results
  6. Generate a concise report
  7. Commit and push only intended changes if safe

The discovery step (finding new businesses via web search) is performed by the
operator using OpenCode web search/browser tools and written to --leads-file.
This script never sends external communications.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from client_acquisition.scripts.crm import CRM
from client_acquisition.scripts.discovery import (
    DEFAULT_THRESHOLD, process_discovered_lead,
)
from client_acquisition.scripts.git_sync import sync


def load_discovered_leads(path: Optional[Path]) -> List[Dict[str, Any]]:
    if not path:
        return []
    if not path.exists():
        print(f"Leads file not found: {path}", file=sys.stderr)
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"Failed to parse leads file: {exc}", file=sys.stderr)
        return []
    if isinstance(data, dict):
        data = data.get("leads", [])
    return data if isinstance(data, list) else []


def run(root: Path, leads_file: Optional[Path] = None,
        no_sync: bool = False,
        threshold: Optional[int] = None) -> int:
    crm = CRM(root)
    threshold = threshold if threshold is not None else DEFAULT_THRESHOLD

    print("=== Client Acquisition: recurring batch ===")
    print(f"Root: {root}")
    print(f"Threshold: {threshold}")
    print()

    # Step 1: Inspect Git status
    print("[1/7] Inspecting Git status and CRM state...")
    stats = crm.stats()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    print()

    # Step 2: Sync safely
    if not no_sync:
        print("[2/7] Synchronizing with remote (safe, no --force)...")
        sync_result = sync(root)
        for line in sync_result.details:
            print(f"  {line}")
        print(f"  Result: {sync_result.message}")
        if not sync_result.success:
            print("  WARNING: Sync failed. Local results are preserved. Continuing with local state.", file=sys.stderr)
        print()
    else:
        print("[2/7] Skipping sync (--no-sync).")
        print()

    # Step 3: Validate existing records
    print("[3/7] Validating existing records...")
    validation = crm.validate()
    total_invalid = sum(v["malformed"] + v["schema_invalid"] for v in validation.values())
    print(f"  Total records: {validation['leads']['total'] + validation['proposals']['total']}")
    print(f"  Invalid/malformed: {total_invalid}")
    if total_invalid > 0:
        print("  WARNING: Malformed/invalid records detected (reported, not deleted).", file=sys.stderr)
    print()

    # Step 4: Process discovered leads
    discovered = load_discovered_leads(leads_file)
    print(f"[4/7] Processing {len(discovered)} discovered leads (limit check)...")
    max_per_run = int(crm.config.get("discovery", {}).get("max_businesses_per_run", 10))
    to_process = discovered[:max_per_run]
    if len(discovered) > max_per_run:
        print(f"  WARNING: {len(discovered)} leads found, capping at {max_per_run} per run.", file=sys.stderr)

    results = []
    for lead in to_process:
        res = process_discovered_lead(crm, lead, threshold=threshold)
        results.append(res)
        status = []
        if res["suppressed"]:
            status.append("SUPPRESSED")
        if res["duplicate"]:
            status.append("DUPLICATE")
        if res["added"]:
            status.append("ADDED")
        if res["proposal_created"]:
            status.append("PROPOSAL")
        print(f"  {res['lead_key']} | {res['business_name']} | score={res['score']} | {' | '.join(status) or 'SKIPPED'} | {res['reason']}")
    print()

    # Step 5: Save and validate results
    print("[5/7] Saving and validating results...")
    # CRM writes are atomic and already persisted. Re-validate.
    validation2 = crm.validate()
    total_invalid2 = sum(v["malformed"] + v["schema_invalid"] for v in validation2.values())
    print(f"  Invalid/malformed after run: {total_invalid2}")
    print()

    # Step 6: Generate report
    print("[6/7] Generating report...")
    from client_acquisition.scripts.report import main as report_main
    # Reuse export via CRM directly for consistent output
    out_path = crm.export_report()
    print(f"  Report: {out_path}")
    print()

    # Step 7: Commit and push
    print("[7/7] Committing and pushing intended changes...")
    sync_result = sync(root)
    for line in sync_result.details:
        print(f"  {line}")
    print(f"  Result: {sync_result.message}")
    if not sync_result.success:
        print("  WARNING: Push failed. Local CRM data is preserved and safe.", file=sys.stderr)

    print()
    print("=== Batch complete ===")
    print(f"Leads processed: {len(results)}")
    print(f"Added: {sum(1 for r in results if r['added'])}")
    print(f"Proposals drafted: {sum(1 for r in results if r['proposal_created'])}")
    print(f"Suppressed: {sum(1 for r in results if r['suppressed'])}")
    print(f"Duplicates skipped: {sum(1 for r in results if r['duplicate'])}")
    print()
    print("Next command: inspect drafts in client_acquisition/data/proposals.jsonl")
    print("No external messages were sent. All proposals are drafts only.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Client acquisition recurring batch")
    parser.add_argument("--leads-file", type=str, default=None,
                        help="Path to JSON file of discovered leads (from web search)")
    parser.add_argument("--no-sync", action="store_true",
                        help="Skip GitHub synchronization")
    parser.add_argument("--threshold", type=int, default=None,
                        help="Override proposal score threshold")
    args = parser.parse_args(argv)
    return run(Path.cwd(),
               leads_file=Path(args.leads_file) if args.leads_file else None,
               no_sync=args.no_sync,
               threshold=args.threshold)


if __name__ == "__main__":
    sys.exit(main())
