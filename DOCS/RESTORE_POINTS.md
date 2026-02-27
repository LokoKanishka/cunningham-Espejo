# Restore Points

## 2026-02-27 - Pre-Reader-Split Checkpoint

- Purpose: freeze current audio/STT/UI state before implementing split Chat vs Reader screens.
- Branch: `main`
- Commit: `4d3b9c4544f2a874a9fcfcb1f06108b34951c798`
- Tag: `restore/pre-reader-split-20260227`
- UTC: `2026-02-27T23:07:55Z`

### What this checkpoint contains

- STT memory workflow and baseline artifacts.
- Voice mode toggle (`stable` / `experimental`) in DC.
- Reader behavior fixes and regression tests currently in workspace.

### How to return here if needed

```bash
git fetch --tags origin
git checkout main
git reset --hard restore/pre-reader-split-20260227
```

### Safer alternative (without reset)

```bash
git fetch --tags origin
git checkout -b rollback/pre-reader-split restore/pre-reader-split-20260227
```
