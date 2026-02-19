#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-8787}"
BASE="http://127.0.0.1:${PORT}"
TMP_DIR="$(mktemp -d)"
MODELS_JSON="${TMP_DIR}/models.json"

cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify direct chat models ==" >&2
echo "target=${BASE}" >&2

if ! curl -fsS -m 2 "${BASE}/api/models" > "${MODELS_JSON}" 2>/dev/null; then
  echo "direct chat no responde; iniciando en puerto ${PORT}..." >&2
  "${ROOT}/scripts/openclaw_direct_chat.sh" "${PORT}" >/dev/null
fi

ok_ready=0
for _ in $(seq 1 20); do
  if curl -fsS -m 3 "${BASE}/api/models" > "${MODELS_JSON}" 2>/dev/null; then
    ok_ready=1
    break
  fi
  sleep 1
done
if [ "${ok_ready}" -ne 1 ]; then
  echo "FAIL: direct chat no quedó disponible en ${BASE}" >&2
  exit 1
fi

mapfile -t MODEL_LINES < <(
  python3 - "${MODELS_JSON}" <<'PY'
import json,sys
p=sys.argv[1]
data=json.load(open(p,encoding="utf-8"))
models=data.get("models",[])
if not isinstance(models,list):
    sys.exit(0)
for m in models:
    if not isinstance(m,dict):
        continue
    mid=str(m.get("id","")).strip()
    if not mid:
        continue
    backend=str(m.get("backend","cloud")).strip() or "cloud"
    available=1 if bool(m.get("available",False)) else 0
    print(f"{mid}\t{backend}\t{available}")
PY
)

if [ "${#MODEL_LINES[@]}" -eq 0 ]; then
  echo "FAIL: /api/models devolvió cero modelos" >&2
  exit 1
fi

allow_vision="${DIRECT_CHAT_ALLOW_VISION:-0}"
allow_vision="$(printf "%s" "${allow_vision}" | tr '[:upper:]' '[:lower:]')"
for line in "${MODEL_LINES[@]}"; do
  model="$(printf "%s" "${line}" | awk -F '\t' '{print $1}')"
  low="$(printf "%s" "${model}" | tr '[:upper:]' '[:lower:]')"
  if printf "%s" "${low}" | grep -qE 'embed|embedding'; then
    echo "FAIL: modelo embedding en catalogo de chat: ${model}" >&2
    exit 1
  fi
  if printf "%s" "${low}" | grep -q 'vision'; then
    if [ "${allow_vision}" != "1" ] && [ "${allow_vision}" != "true" ] && [ "${allow_vision}" != "yes" ] && [ "${allow_vision}" != "on" ]; then
      echo "FAIL: modelo vision presente sin DIRECT_CHAT_ALLOW_VISION=1: ${model}" >&2
      exit 1
    fi
  fi
done

pass_count=0
warn_count=0
fail_count=0

for line in "${MODEL_LINES[@]}"; do
  model="$(printf "%s" "${line}" | awk -F '\t' '{print $1}')"
  backend="$(printf "%s" "${line}" | awk -F '\t' '{print $2}')"
  available="$(printf "%s" "${line}" | awk -F '\t' '{print $3}')"

  if [ "${backend}" = "local" ] && [ "${available}" != "1" ]; then
    echo "WARN_MISSING_MODEL model=${model} backend=${backend}" >&2
    warn_count=$((warn_count + 1))
    continue
  fi

  body_file="${TMP_DIR}/body.json"
  python3 - "${model}" "${backend}" "${body_file}" <<'PY'
import json,sys
model,backend,path=sys.argv[1],sys.argv[2],sys.argv[3]
payload={
  "message":"Respondé exactamente OK",
  "model":model,
  "model_backend":backend,
  "history":[],
  "mode":"conciso",
  "session_id":f"verify_dc_{backend}",
  "allowed_tools":[],
  "attachments":[],
}
open(path,"w",encoding="utf-8").write(json.dumps(payload,ensure_ascii=False))
PY

  resp_file="${TMP_DIR}/resp.json"
  meta_file="${TMP_DIR}/meta.txt"
  curl -sS -m 120 \
    -H "Content-Type: application/json" \
    -o "${resp_file}" \
    -w "HTTP_STATUS:%{http_code}\nTOTAL_TIME:%{time_total}\n" \
    -d @"${body_file}" \
    "${BASE}/api/chat" > "${meta_file}"

  http_status="$(awk -F: '/^HTTP_STATUS:/{print $2}' "${meta_file}" | tr -d '[:space:]')"
  total_time="$(awk -F: '/^TOTAL_TIME:/{print $2}' "${meta_file}" | tr -d '[:space:]')"

  if [ "${http_status}" != "200" ]; then
    echo "FAIL model=${model} backend=${backend} http=${http_status} sec=${total_time}" >&2
    head -c 240 "${resp_file}" >&2 || true
    echo >&2
    fail_count=$((fail_count + 1))
    continue
  fi

  parsed="$(python3 - "${resp_file}" <<'PY'
import json,sys
raw=json.load(open(sys.argv[1],encoding="utf-8"))
reply=str(raw.get("reply",""))
backend=str(raw.get("model_backend",""))
model=str(raw.get("model",""))
print(f"{backend}\t{model}\t{len(reply.strip())}")
PY
)"
  got_backend="$(printf "%s" "${parsed}" | awk -F '\t' '{print $1}')"
  got_model="$(printf "%s" "${parsed}" | awk -F '\t' '{print $2}')"
  reply_len="$(printf "%s" "${parsed}" | awk -F '\t' '{print $3}')"

  if [ -z "${reply_len}" ] || [ "${reply_len}" -le 0 ]; then
    echo "FAIL model=${model} backend=${backend} empty_reply sec=${total_time}" >&2
    fail_count=$((fail_count + 1))
    continue
  fi

  echo "PASS model=${model} backend=${backend} via=${got_backend}/${got_model} http=${http_status} sec=${total_time}" >&2
  pass_count=$((pass_count + 1))
done

if [ "${pass_count}" -eq 0 ]; then
  echo "FAIL: no hubo modelos testeables (warn=${warn_count})" >&2
  exit 1
fi

if [ "${fail_count}" -gt 0 ]; then
  echo "FAIL: dc models check falló (pass=${pass_count} warn=${warn_count} fail=${fail_count})" >&2
  exit 1
fi

echo "DC_MODELS_OK pass=${pass_count} warn=${warn_count} fail=${fail_count}" >&2
