"""Validate CRM JSONL data files.

Usage:
    python -m client_acquisition.scripts.validate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from client_acquisition.scripts.crm import CRM, _HAS_JSONSCHEMA


def main() -> int:
    crm = CRM(Path.cwd())
    result = crm.validate()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    total_invalid = sum(v["malformed"] + v["schema_invalid"] for v in result.values())
    if total_invalid > 0:
        print(f"\nVALIDATION FAILED: {total_invalid} invalid/malformed records found.", file=sys.stderr)
        return 1
    print("\nVALIDATION PASSED: all records are well-formed.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
