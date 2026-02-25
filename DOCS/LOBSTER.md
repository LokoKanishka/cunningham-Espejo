# Lobster in this repo

## What it is
- OpenClaw plugin tool id: `lobster`.
- Runs local `lobster` subprocess with typed JSON envelopes.
- Main actions from plugin code:
  - `action: run` => `lobster run --mode tool <pipeline> [--args-json ...]`
  - `action: resume` => `lobster resume --token <token> --approve yes|no`

## Security notes (from local plugin code)
- Tool is not registered when `ctx.sandboxed` is true.
- `cwd` must be relative and remain inside gateway working dir.
- Limits include timeout and max stdout bytes.
- `lobsterPath` override must be absolute and point to `lobster` executable.

## Local verify
```bash
./scripts/verify_lobster.sh
```

What it validates:
1. `lobster` binary exists in PATH.
2. OpenClaw plugin `lobster` is loaded.
3. A real tool-mode run returns a valid JSON envelope.
4. If status is `needs_approval`, envelope contains `resumeToken`.

## Notes
- This verify is local-only and does not require paid API keys.
- Keep plugin allowlist enforced via `scripts/verify_plugins.sh`.
