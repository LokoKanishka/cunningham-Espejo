#!/usr/bin/env bash
set -euo pipefail

# --- Config ---
URL="${URL:-http://127.0.0.1:5678/healthz}"
N="${N:-2000}"           # cantidad de requests
P="${P:-50}"             # concurrencia (xargs -P)
TIMEOUT="${TIMEOUT:-5}"  # segundos por request
OK_RATE_MIN="${OK_RATE_MIN:-0.995}"

OUTDIR="${OUTDIR:-./_stress}"
mkdir -p "$OUTDIR"
TS="$(date +%Y%m%d_%H%M%S)"
RAW="$OUTDIR/raw_${TS}.csv"
META="$OUTDIR/meta_${TS}.txt"
SUMMARY="$OUTDIR/summary_${TS}.txt"
METRICS_BEFORE="$OUTDIR/metrics_before_${TS}.txt"
METRICS_AFTER="$OUTDIR/metrics_after_${TS}.txt"
STATS_BEFORE="$OUTDIR/docker_stats_before_${TS}.txt"
STATS_AFTER="$OUTDIR/docker_stats_after_${TS}.txt"
LOGS="$OUTDIR/docker_logs_${TS}.txt"

START_ISO="$(date --iso-8601=seconds)"

wait_ready() {
  local tries="${1:-30}"
  local sleep_s="${2:-1}"
  for i in $(seq 1 "$tries"); do
    local code
    code="$(curl -sS -o /dev/null -m "$TIMEOUT" -w "%{http_code}" "$URL" 2>/dev/null || true)"
    if [[ -n "${code:-}" && "$code" != "000" ]]; then
      echo "READY url=$URL http=$code (t=${i}s)"
      return 0
    fi
    sleep "$sleep_s"
  done
  echo "NOT_READY url=$URL after ${tries}s"
  return 1
}

{
  echo "START_ISO=$START_ISO"
  echo "URL=$URL"
  echo "N=$N P=$P TIMEOUT=$TIMEOUT OK_RATE_MIN=$OK_RATE_MIN"
  echo
  docker ps -a --filter name=lucy_brain_n8n --format 'Name={{.Names}} Status={{.Status}} Image={{.Image}}'
  echo
} > "$META"

wait_ready 30 1

# snapshots antes
(curl -sS -m "$TIMEOUT" http://127.0.0.1:5678/metrics > "$METRICS_BEFORE" 2>/dev/null) || true
(docker stats --no-stream lucy_brain_n8n > "$STATS_BEFORE" 2>/dev/null) || true

# disparamos N requests en paralelo y guardamos "http_code,time_total"
# si curl falla: 000,timeout
seq 1 "$N" | xargs -P "$P" -I{} sh -c \
  'curl -sS -o /dev/null -m '"$TIMEOUT"' -w "%{http_code},%{time_total}\n" "'"$URL"'" 2>/dev/null || echo "000,'"${TIMEOUT}.000"'"' \
  >> "$RAW"

# snapshots después
(curl -sS -m "$TIMEOUT" http://127.0.0.1:5678/metrics > "$METRICS_AFTER" 2>/dev/null) || true
(docker stats --no-stream lucy_brain_n8n > "$STATS_AFTER" 2>/dev/null) || true
(docker logs --since "$START_ISO" lucy_brain_n8n > "$LOGS" 2>/dev/null) || true

export RAW SUMMARY
python3 - <<'PY'
import csv, math
from collections import Counter
from pathlib import Path
import os

raw = Path(os.environ["RAW"])
rows = [r for r in csv.reader(raw.read_text().splitlines()) if r]
codes = [r[0].strip() for r in rows]
times = []
for r in rows:
    try:
        times.append(float(r[1]))
    except Exception:
        pass

total = len(codes)
ok = sum(1 for c in codes if c.startswith("2"))
fail = total - ok
ok_rate = (ok/total) if total else 0.0

times_sorted = sorted(times)
def q(p):
    if not times_sorted:
        return None
    i = max(0, min(len(times_sorted)-1, int(math.ceil(p*len(times_sorted))) - 1))
    return times_sorted[i]

cnt = Counter(codes)
top = ", ".join([f"{k}:{v}" for k,v in cnt.most_common(8)])

out = []
out.append(f"TOTAL={total} OK_2xx={ok} FAIL={fail} OK_RATE={ok_rate:.4f}")
if times_sorted:
    out.append(f"LATENCY_S: p50={q(0.50):.3f} p95={q(0.95):.3f} p99={q(0.99):.3f} max={times_sorted[-1]:.3f} mean={sum(times_sorted)/len(times_sorted):.3f}")
out.append(f"CODES_TOP={top}")
print("\n".join(out))

# exitcode via file marker
summary = Path(os.environ["SUMMARY"])
summary.write_text("\n".join(out) + "\n", encoding="utf-8")
summary.with_suffix(".okrate").write_text(str(ok_rate), encoding="utf-8")
PY

OK_RATE="$(cat "${SUMMARY%.txt}.okrate" 2>/dev/null || echo 0)"
python3 - <<PY
ok=float("$OK_RATE")
thr=float("$OK_RATE_MIN")
print("PASS" if ok>=thr else "FAIL", "ok_rate=",f"{ok:.4f}","threshold=",f"{thr:.4f}")
PY

echo
echo "Artifacts:"
echo "  $META"
echo "  $SUMMARY"
echo "  $RAW"
echo "  $METRICS_BEFORE"
echo "  $METRICS_AFTER"
echo "  $STATS_BEFORE"
echo "  $STATS_AFTER"
echo "  $LOGS"
