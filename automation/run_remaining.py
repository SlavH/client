#!/usr/bin/env python3
"""Generate all remaining demos in 10-site batches and push after each batch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEADS = ROOT / "client_acquisition" / "data" / "leads.jsonl"
START = int(sys.argv[1]) if len(sys.argv) > 1 else 10
BATCH = 10

leads = [json.loads(line) for line in LEADS.read_text(encoding="utf-8").splitlines() if line.strip()]
total = len(leads)


def run_batch(indices: list[int]) -> list[str]:
    procs = []
    for idx in indices:
        proc = subprocess.Popen(
            [sys.executable, "automation/generate_demo.py", "--index", str(idx)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        procs.append((idx, proc))
    failures = []
    for idx, proc in procs:
        out, err = proc.communicate()
        if proc.returncode != 0:
            failures.append(f"index {idx}: {err.strip() or out.strip()}")
    return failures


def git(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


for batch_no, start in enumerate(range(START, total, BATCH), start=1):
    indices = list(range(start, min(start + BATCH, total)))
    print(f"batch {batch_no}: indices {indices[0]}..{indices[-1]} ({len(indices)} sites)", flush=True)
    failures = run_batch(indices)
    if failures:
        print("FAILURES:", flush=True)
        for failure in failures:
            print(failure, flush=True)

    rc, out, err = git("add", "business-demos")
    if rc != 0:
        print(f"git add failed: {err}", flush=True)
        break
    rc, out, err = git("commit", "-m", f"feat(demos): add static concept demos batch {batch_no}")
    if rc != 0 and "nothing to commit" not in (out + err).lower():
        print(f"git commit failed: {err or out}", flush=True)
        break
    rc, out, err = git("push", "origin", "master")
    if rc != 0:
        print(f"git push failed: {err or out}", flush=True)
        break
    print(f"pushed batch {batch_no}", flush=True)

print("completed generator run", flush=True)
