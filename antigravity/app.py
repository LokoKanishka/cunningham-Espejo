from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import List, Optional

import subprocess
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Antigravity Sandbox")

WORKSPACE_ROOT = Path(os.environ.get("ANTIGRAVITY_WORKSPACE", "/workspace"))
RUNS_DIR = WORKSPACE_ROOT / "antigravity_runs"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DEFAULT_TIMEOUT_S = _env_int("ANTIGRAVITY_DEFAULT_TIMEOUT_S", 30)
MAX_TIMEOUT_S = _env_int("ANTIGRAVITY_MAX_TIMEOUT_S", 30)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


class ExecuteRequest(BaseModel):
    code: str = Field(..., description="Python code to execute")
    timeout_s: Optional[int] = Field(
        None, description="Optional timeout override in seconds"
    )


class ExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    returncode: int
    artifacts: List[str]
    run_dir: str


def _effective_timeout(requested: Optional[int]) -> int:
    req = DEFAULT_TIMEOUT_S if requested is None else max(1, int(requested))
    return min(req, MAX_TIMEOUT_S)


def _guard_code(code: str) -> None:
    # Minimal guardrail: reject obviously destructive commands.
    if "rm -rf /" in code:
        raise HTTPException(status_code=400, detail="Dangerous command rejected.")


def _collect_artifacts(run_dir: Path) -> List[str]:
    artifacts: List[str] = []
    for root, _, files in os.walk(run_dir):
        for name in files:
            rel = Path(root, name).relative_to(run_dir)
            if rel.name == "run.py":
                continue
            artifacts.append(str(rel))
    return artifacts


@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest) -> ExecuteResponse:
    _guard_code(req.code)

    run_id = uuid.uuid4().hex
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    run_file = run_dir / "run.py"
    run_file.write_text(req.code, encoding="utf-8")

    timeout_s = _effective_timeout(req.timeout_s)

    try:
        completed = subprocess.run(
            [sys.executable, str(run_file)],
            capture_output=True,
            text=True,
            cwd=str(run_dir),
            timeout=timeout_s,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        rc = completed.returncode if completed.returncode is not None else 0
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTimed out after {timeout_s}s."
        rc = 124

    artifacts = _collect_artifacts(run_dir)

    return ExecuteResponse(
        stdout=stdout,
        stderr=stderr,
        returncode=rc,
        artifacts=artifacts,
        run_dir=str(run_dir),
    )
