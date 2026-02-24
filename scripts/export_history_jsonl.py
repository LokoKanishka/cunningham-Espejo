#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export direct_chat_histories JSON files to JSONL dataset")
    p.add_argument("--in", dest="input_dir", required=True, help="Input directory with history JSON files")
    p.add_argument("--out", dest="output_file", required=True, help="Output JSONL file path")
    p.add_argument("--mode", choices=("pairs", "messages"), default="pairs", help="Export format")
    p.add_argument("--min-chars", type=int, default=1, help="Minimum chars for prompt and completion")
    p.add_argument("--max-sessions", type=int, default=0, help="Maximum number of files to process; 0 = unlimited")
    p.add_argument("--max-lines", type=int, default=0, help="Maximum lines to write; 0 = unlimited")
    p.add_argument("--since-days", type=int, default=0, help="Only include files modified in last N days; 0 = disabled")
    p.add_argument("--max-completion-chars", type=int, default=0, help="Max chars for completion; 0 = unlimited")
    return p.parse_args()


def parse_meta(filename: str) -> tuple[str, str, str]:
    stem = Path(filename).stem
    parts = stem.split("__", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return stem, "", ""


def load_history(path: Path) -> tuple[list[dict], bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], True
    if not isinstance(data, list):
        return [], True
    out: list[dict] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
    return out, False


def iter_pairs(messages: list[dict], min_chars: int, counters: dict[str, int]):
    pending_user: str | None = None
    for item in messages:
        role = str(item.get("role", "")).strip().lower()
        if role not in ("user", "assistant"):
            counters["invalid_role_dropped"] += 1
            continue

        content = item.get("content", "")
        if not isinstance(content, str):
            counters["invalid_content_dropped"] += 1
            continue

        content = content.strip()
        if not content:
            counters["empty_dropped"] += 1
            continue

        if role == "user":
            if pending_user is not None:
                counters["user_overwritten"] += 1
                counters["orphan_user_dropped"] += 1
            pending_user = content
            continue

        if pending_user is None:
            counters["assistant_without_user_dropped"] += 1
            continue

        prompt = pending_user.strip()
        completion = content.strip()
        pending_user = None

        if len(prompt) < min_chars:
            counters["short_prompt_dropped"] += 1
            continue
        if len(completion) < min_chars:
            counters["short_completion_dropped"] += 1
            continue

        yield prompt, completion

    if pending_user is not None:
        counters["orphan_user_dropped"] += 1


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser()
    output_file = Path(args.output_file).expanduser()
    min_chars = max(0, int(args.min_chars))
    max_sessions = max(0, int(args.max_sessions))
    max_lines = max(0, int(args.max_lines))
    since_days = max(0, int(args.since_days))
    max_completion_chars = max(0, int(args.max_completion_chars))

    files = sorted([p for p in input_dir.glob("*.json") if p.is_file()])
    sessions_total = len(files)

    if since_days > 0:
        cutoff = time.time() - (since_days * 86400)
        files = [p for p in files if p.stat().st_mtime >= cutoff]

    if max_sessions > 0:
        files = files[:max_sessions]

    output_file.parent.mkdir(parents=True, exist_ok=True)

    counters = {
        "invalid_role_dropped": 0,
        "invalid_content_dropped": 0,
        "empty_dropped": 0,
        "assistant_without_user_dropped": 0,
        "orphan_user_dropped": 0,
        "user_overwritten": 0,
        "short_prompt_dropped": 0,
        "short_completion_dropped": 0,
        "completion_truncated": 0,
    }
    files_invalid_json = 0
    rows = 0
    rows_by_session: dict[str, int] = {}
    pairs_per_backend_model: dict[str, dict[str, int]] = {}

    with output_file.open("w", encoding="utf-8") as f:
        stop = False
        for path in files:
            session_id, backend, model = parse_meta(path.name)
            history, invalid_json = load_history(path)
            if invalid_json:
                files_invalid_json += 1
                continue
            for prompt, completion in iter_pairs(history, min_chars=min_chars, counters=counters):
                if max_completion_chars > 0 and len(completion) > max_completion_chars:
                    completion = completion[:max_completion_chars]
                    counters["completion_truncated"] += 1
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
                rows_by_session[session_id] = rows_by_session.get(session_id, 0) + 1
                backend_map = pairs_per_backend_model.setdefault(backend, {})
                backend_map[model] = backend_map.get(model, 0) + 1

                if max_lines > 0 and rows >= max_lines:
                    stop = True
                    break
            if stop:
                break

    top_sessions = sorted(rows_by_session.items(), key=lambda item: (-item[1], item[0]))[:10]

    summary = {
        "ok": True,
        "mode": args.mode,
        "rows": rows,
        "sessions_total": sessions_total,
        "sessions_scanned": len(files),
        "sessions_with_rows": len(rows_by_session),
        "files_invalid_json": files_invalid_json,
        "in": str(input_dir),
        "out": str(output_file),
        "filters": {
            "min_chars": min_chars,
            "max_sessions": max_sessions,
            "max_lines": max_lines,
            "since_days": since_days,
            "max_completion_chars": max_completion_chars,
        },
        "dropped": counters,
        "pairs_per_backend_model": pairs_per_backend_model,
        "top_sessions": [{"session_id": sid, "rows": cnt} for sid, cnt in top_sessions],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
