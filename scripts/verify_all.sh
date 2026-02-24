#!/usr/bin/env bash
set -euo pipefail

echo "== verify_gateway ==" >&2
./scripts/verify_gateway.sh
echo "== verify_plugins ==" >&2
./scripts/verify_plugins.sh 1>&2
echo "== verify_lobster ==" >&2
./scripts/verify_lobster.sh 1>&2

echo "== verify_capabilities ==" >&2
./scripts/verify_capabilities.sh 1>&2

echo "== verify_reader_mode ==" >&2
./scripts/verify_reader_mode.sh

echo "== verify_reader_mode_v01 ==" >&2
./scripts/verify_reader_mode_v01.sh

echo "== verify_reader_library ==" >&2
./scripts/verify_reader_library.sh

echo "== verify_reader_ux_dc ==" >&2
./scripts/verify_reader_ux_dc.sh

echo "== verify_stt_barge_in_smoke ==" >&2
./scripts/verify_stt_barge_in_smoke.sh

echo "== verify_slash_reader_ui ==" >&2
./scripts/verify_slash_reader_ui.sh

echo "== verify_history_export ==" >&2
./scripts/verify_history_export.sh

echo "== verify_codex_subscription ==" >&2
./scripts/verify_codex_subscription.sh

echo "== verify_security_audit ==" >&2
./scripts/verify_security_audit.sh

echo "== verify_community_mcp ==" >&2
./scripts/community_mcp.sh check 1>&2

if [ "${VERIFY_DC_UI_MODELS:-0}" = "1" ]; then
  echo "== verify_dc_ui_models ==" >&2
  node ./scripts/verify_dc_ui_models.js
fi

if [ "${VERIFY_READER_UI_HUMAN:-0}" = "1" ]; then
  echo "== verify_reader_ui_human ==" >&2
  node ./scripts/verify_reader_ui_human.js
fi

echo "ALL_OK" >&2
