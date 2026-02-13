#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: contract_validate.py <schema.json> <instance.json>", file=sys.stderr)
        return 2

    schema_path = Path(sys.argv[1])
    instance_path = Path(sys.argv[2])

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    instance = json.loads(instance_path.read_text(encoding="utf-8"))

    try:
        import jsonschema
    except Exception as exc:  # pragma: no cover
        print(f"ERROR jsonschema_import_failed: {exc}", file=sys.stderr)
        print("Install with: python3 -m pip install --user jsonschema", file=sys.stderr)
        return 3

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
    if errors:
        print("VALIDATION=FAIL")
        for err in errors:
            p = "/".join(str(x) for x in err.path)
            p = p if p else "<root>"
            print(f"- path={p} message={err.message}")
        return 1

    print("VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
