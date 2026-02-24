#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export direct_chat_histories JSON files to JSONL dataset")
    p.add_argument("--in", dest="input_dir", required=True, help="Input directory with history JSON files")
    p.add_argument("--out", dest="output_file", required=True, help="Output JSONL file path")
    p.add_argument("--mode", choices=("pairs", "messages"), default="pairs", help="Export format")
    p.add_argument("--min-chars", type=int, default=1, help="Minimum chars for prompt and completion")
    p.add_argument("--max-sessions", type=int, default=0, help="Maximum number of files to process; 0 = unlimited")
    return p.parse_args()


def parse_meta(filename: str) -> tuple[str, str, str]:
    stem = Path(filename).stem
    parts = stem.split("__", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return stem, "", ""


def iter_pairs(messages: list[dict], min_chars: int):
    pending_user: str | None = None
    for item in messages:
        role = str(item.get("role", "")).strip().lower()
        if role not in ("user", "assistant"):
            continue
        content = item.get("content", "")
        if not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue

        if role == "user":
            pending_user = content
            continue

        if pending_user is None:
            continue

        prompt = pending_user.strip()
        completion = content.strip()
        pending_user = None
        if len(prompt) < min_chars or len(completion) < min_chars:
            continue
        yield prompt, completion


def load_history(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
    return out


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser()
    output_file = Path(args.output_file).expanduser()
    min_chars = max(0, int(args.min_chars))
    max_sessions = int(args.max_sessions)

    files = sorted([p for p in input_dir.glob("*.json") if p.is_file()])
    if max_sessions > 0:
        files = files[:max_sessions]

    output_file.parent.mkdir(parents=True, exist_ok=True)

    rows = 0
    with output_file.open("w", encoding="utf-8") as f:
        for path in files:
            session_id, backend, model = parse_meta(path.name)
            history = load_history(path)
            for prompt, completion in iter_pairs(history, min_chars=min_chars):
                base = {
                    "session_id": session_id,
                    "backend": backend,
                    "model": model,
                    "source_file": path.name,
                }
                if args.mode == "pairs":
                    row = {**base, "prompt": prompt, "completion": completion}
                else:
                    row = {
                        **base,
                        "messages": [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": completion},
                        ],
                    }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows += 1

    print(
        json.dumps(
            {
                "ok": True,
                "mode": args.mode,
                "rows": rows,
                "sessions_scanned": len(files),
                "in": str(input_dir),
                "out": str(output_file),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
