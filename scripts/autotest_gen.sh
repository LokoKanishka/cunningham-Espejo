#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-check}"
shift || true

case "$cmd" in
  check)
    [ -x ./scripts/verify_all.sh ] || { echo "verify_all missing" >&2; exit 1; }
    echo "AUTOTEST_GEN_OK"
    ;;
  run)
    ./scripts/verify_all.sh
    if [ -x ./scripts/verify_stack10.sh ]; then
      ./scripts/verify_stack10.sh
    fi
    echo "AUTOTEST_RUN_OK"
    ;;
  scaffold)
    cat > scripts/test_changed_files.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
git diff --name-only | sed '/^$/d' || true
SH
    chmod +x scripts/test_changed_files.sh
    echo "SCAFFOLD_OK"
    ;;
  *)
    echo "usage: $0 {check|run|scaffold}" >&2
    exit 2
    ;;
esac
