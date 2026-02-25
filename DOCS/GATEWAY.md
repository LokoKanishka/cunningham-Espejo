# Gateway Runbook

## Goal
Ensure commands use the current OpenClaw config/model state and do not silently fall back to stale legacy daemons.

## Fast checks
```bash
export PATH="$HOME/.openclaw/bin:$PATH"
openclaw status
openclaw gateway status
```

## Known pitfall
If `clawdbot-gateway` is active on `127.0.0.1:18789`, agent turns can use old model/provider settings (e.g. `ollama`) even when `openclaw` defaults are set to `openai-codex/...`.

## Remediation
```bash
systemctl --user disable --now clawdbot-gateway.service clawdbot-node.service
nohup openclaw gateway --force > "$HOME/.openclaw/gateway-foreground.log" 2>&1 &
openclaw health
```

## Verify
```bash
./scripts/verify_gateway.sh
./scripts/verify_all.sh
```
