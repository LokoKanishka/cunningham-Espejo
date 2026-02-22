import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTER_SCRIPT = REPO_ROOT / "scripts" / "model_router.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class TestModelRouterScript(unittest.TestCase):
    def test_check_command(self) -> None:
        proc = subprocess.run(
            ["bash", str(ROUTER_SCRIPT), "check"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("MODEL_ROUTER_OK", proc.stdout)

    def test_ask_with_fallback_picks_installed_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="router_test_") as td:
            tmp = Path(td)
            home = tmp / "home"
            bin_dir = home / ".openclaw" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)

            log_path = tmp / "openclaw.log"
            count_path = tmp / "agent_count.txt"
            count_path.write_text("0", encoding="utf-8")

            _write_executable(
                bin_dir / "openclaw",
                """#!/usr/bin/env bash
set -euo pipefail
LOG="${TEST_OPENCLAW_LOG:?}"
COUNT_FILE="${TEST_OPENCLAW_COUNT:?}"
printf '%s\\n' "$*" >> "$LOG"

if [[ "${1:-}" == "models" && "${2:-}" == "set" ]]; then
  exit 0
fi

if [[ "${1:-}" == "agent" ]]; then
  if [[ "$*" == *"--json"* ]]; then
    c="$(cat "$COUNT_FILE")"
    n=$((c+1))
    echo "$n" > "$COUNT_FILE"
    if [[ "$n" -eq 1 ]]; then
      echo "429 rate limit"
    else
      echo "ANSWER_OK"
    fi
    exit 0
  fi
  exit 0
fi

exit 0
""",
            )

            _write_executable(
                bin_dir / "ollama",
                """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "list" ]]; then
  cat <<'EOF'
NAME ID SIZE MODIFIED
mistral-uncensored:latest abc 1GB now
EOF
  exit 0
fi
exit 1
""",
            )

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["TEST_OPENCLAW_LOG"] = str(log_path)
            env["TEST_OPENCLAW_COUNT"] = str(count_path)

            proc = subprocess.run(
                ["bash", str(ROUTER_SCRIPT), "ask-with-fallback", "mensaje simple"],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
            )

            combined = f"{proc.stdout}\n{proc.stderr}".strip()
            self.assertEqual(proc.returncode, 0, msg=combined)
            self.assertIn("ANSWER_OK", combined)

            log = log_path.read_text(encoding="utf-8")
            self.assertIn("models set openai-codex/gpt-5.1-codex-mini", log)
            self.assertIn("models set ollama/mistral-uncensored:latest", log)
            self.assertNotIn("models set ollama/gpt-oss:20b", log)


if __name__ == "__main__":
    unittest.main()
