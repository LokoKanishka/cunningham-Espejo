#!/usr/bin/env python3
import os
import sys
import time
import pathlib
import subprocess
import shlex

IPC_DIR = os.environ.get(
    "X11_FILE_IPC_DIR", "/home/lucy-ubuntu/Lucy_Workspace/infra/ipc"
)

IPC = pathlib.Path(IPC_DIR)
INBOX = IPC / "inbox"
OUTBOX = IPC / "outbox"
PROCESSED = IPC / "payloads"

for d in (INBOX, OUTBOX, PROCESSED):
    d.mkdir(parents=True, exist_ok=True)

LOG = IPC / "agent.log"

DEFAULT_TIMEOUT = float(os.environ.get("X11_FILE_AGENT_TIMEOUT", "6"))


def log(msg: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(msg.rstrip() + "\n")
    except Exception:
        pass


def run_cmd(cmd: str, timeout_s: float):
    env = os.environ.copy()
    env.pop("X11_FILE_IPC_DIR", None)
    env["X11_FORCE_LOCAL"] = "1"
    wrap_dir = (pathlib.Path(__file__).resolve().parent / "x11_wrap").resolve()
    path_val = env.get("PATH", "")
    if path_val:
        parts = [p for p in path_val.split(":") if p]
        parts = [p for p in parts if os.path.realpath(p) != str(wrap_dir)]
        env["PATH"] = ":".join(parts)
    proc = subprocess.Popen(
        ["bash", "-lc", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        preexec_fn=os.setsid,
    )
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        rc = proc.returncode if proc.returncode is not None else 0
        return rc, out or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 15)
        except Exception:
            pass
        time.sleep(0.15)
        try:
            os.killpg(proc.pid, 9)
        except Exception:
            pass
        return 124, ""


def parse_payload(text: str):
    line = text.strip().splitlines()[0] if text.strip() else ""
    if ":" in line:
        kind, rest = line.split(":", 1)
        return kind.strip().upper(), rest.strip()
    if line:
        return "EXEC", line.strip()
    return "NOOP", ""


def handle_request(path: pathlib.Path) -> None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = ""

    kind, payload = parse_payload(content)
    timeout_s = DEFAULT_TIMEOUT

    if kind == "NOTIFY":
        msg = payload or "Lucy notification"
        cmd = f"notify-send {shlex.quote('Lucy')} {shlex.quote(msg)}"
        rc, out = run_cmd(cmd, timeout_s)
    elif kind == "EXEC":
        rc, out = run_cmd(payload, timeout_s)
    elif kind == "NOOP":
        rc, out = 0, "NOOP\n"
    else:
        rc, out = 2, f"UNKNOWN_COMMAND: {kind}\n"

    response = f"RC={rc}\n"
    if out:
        response += out
        if not response.endswith("\n"):
            response += "\n"

    out_name = f"res_{path.name}"
    out_path = OUTBOX / out_name
    try:
        out_path.write_text(response, encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        path.rename(PROCESSED / path.name)
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass


def main() -> None:
    log(f"x11_file_agent: ipc={IPC}")
    log(f"x11_file_agent: inbox={INBOX}")
    log(f"x11_file_agent: outbox={OUTBOX}")

    while True:
        try:
            reqs = sorted(INBOX.iterdir(), key=lambda p: p.stat().st_mtime)
        except Exception:
            reqs = []

        if not reqs:
            time.sleep(0.1)
            continue

        for req in reqs:
            if not req.is_file():
                continue
            if req.name.startswith(".") or req.name.endswith(".tmp"):
                continue
            handle_request(req)


if __name__ == "__main__":
    if not IPC_DIR:
        print("x11_file_agent: ERROR: IPC dir not set", file=sys.stderr)
        sys.exit(2)
    main()
