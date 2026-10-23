"""Generate a concise CRM report.

Usage:
    python -m client_acquisition.scripts.report [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from client_acquisition.scripts.crm import CRM


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate CRM report")
    parser.add_argument("--out", type=str, default=None, help="Output report path")
    args = parser.parse_args()

    crm = CRM(Path.cwd())
    out = crm.export_report(Path(args.out) if args.out else None)
    print(f"Report written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
