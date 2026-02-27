#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import difflib
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STT_LOCAL_PATH = ROOT / "scripts" / "molbot_direct_chat" / "stt_local.py"
BASELINE_PATH = ROOT / "DOCS" / "STT_BASELINE_CURRENT.json"


def _literal_eval_or_raw(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant):
            return node.value
        return ast.unparse(node)


def read_stt_defaults(path: Path) -> dict[str, Any]:
    src = path.read_text(encoding="utf-8")
    mod = ast.parse(src)
    for node in mod.body:
        if isinstance(node, ast.ClassDef) and node.name == "STTConfig":
            out: dict[str, Any] = {}
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    key = stmt.target.id
                    value = _literal_eval_or_raw(stmt.value) if stmt.value is not None else None
                    out[key] = value
            if not out:
                raise RuntimeError("STTConfig found but no defaults parsed")
            return out
    raise RuntimeError("STTConfig class not found")


def _json_dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def cmd_snapshot(write: bool, baseline_path: Path) -> int:
    current = read_stt_defaults(STT_LOCAL_PATH)
    rendered = _json_dump(current)
    if write:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote baseline: {baseline_path}")
    else:
        print(rendered, end="")
    return 0


def cmd_check(baseline_path: Path) -> int:
    current = read_stt_defaults(STT_LOCAL_PATH)
    if not baseline_path.exists():
        print(f"Baseline missing: {baseline_path}")
        print("Run: python3 scripts/stt_memory_snapshot.py snapshot --write")
        return 2

    expected = json.loads(baseline_path.read_text(encoding="utf-8"))
    if expected == current:
        print("STT_BASELINE_OK")
        return 0

    exp = _json_dump(expected).splitlines(keepends=True)
    cur = _json_dump(current).splitlines(keepends=True)
    print("STT_BASELINE_MISMATCH")
    for line in difflib.unified_diff(exp, cur, fromfile="baseline", tofile="current"):
        print(line, end="")
    print("\nIf this change is intentional, refresh baseline:")
    print("  python3 scripts/stt_memory_snapshot.py snapshot --write")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="STT defaults baseline guardrail")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_snapshot = sub.add_parser("snapshot", help="Print or write current STTConfig defaults")
    p_snapshot.add_argument("--write", action="store_true", help="Write to baseline file")
    p_snapshot.add_argument("--baseline", default=str(BASELINE_PATH), help="Baseline json path")

    p_check = sub.add_parser("check", help="Compare current defaults against baseline")
    p_check.add_argument("--baseline", default=str(BASELINE_PATH), help="Baseline json path")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline = Path(args.baseline)
    if args.cmd == "snapshot":
        return cmd_snapshot(write=bool(args.write), baseline_path=baseline)
    if args.cmd == "check":
        return cmd_check(baseline_path=baseline)
    raise RuntimeError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
