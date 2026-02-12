#!/usr/bin/env bash
set -euo pipefail

store="${GOALS_FILE:-DOCS/GOALS.jsonl}"
mkdir -p "$(dirname "$store")"
cmd="${1:-list}"
shift || true

now() { date -Is; }

case "$cmd" in
  add)
    goal="$*"
    [ -n "$goal" ] || { echo "usage: $0 add <goal text>" >&2; exit 2; }
    id="g$(date +%s%N)"
    printf '{"id":"%s","status":"todo","created_at":"%s","goal":%s}\n' \
      "$id" "$(now)" "$(printf '%s' "$goal" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" >> "$store"
    echo "ADDED:$id"
    ;;
  list)
    [ -f "$store" ] || { echo "[]"; exit 0; }
    cat "$store"
    ;;
  next)
    [ -f "$store" ] || { echo "NO_GOALS"; exit 0; }
    python3 - "$store" <<'PY'
import json,sys
p=sys.argv[1]
for ln in open(p,encoding='utf-8'):
    o=json.loads(ln)
    if o.get('status')=='todo':
        print(json.dumps(o,ensure_ascii=True))
        sys.exit(0)
print('NO_TODO')
PY
    ;;
  done)
    id="${1:-}"
    [ -n "$id" ] || { echo "usage: $0 done <id>" >&2; exit 2; }
    [ -f "$store" ] || { echo "missing $store" >&2; exit 1; }
    python3 - "$store" "$id" <<'PY'
import json,sys
p,i=sys.argv[1],sys.argv[2]
rows=[]
changed=False
for ln in open(p,encoding='utf-8'):
    o=json.loads(ln)
    if o.get('id')==i and o.get('status')!='done':
        o['status']='done'; o['done_at']=__import__('datetime').datetime.now().astimezone().isoformat(); changed=True
    rows.append(o)
open(p,'w',encoding='utf-8').write(''.join(json.dumps(r,ensure_ascii=True)+'\n' for r in rows))
print('DONE' if changed else 'NO_CHANGE')
PY
    ;;
  check)
    echo "GOALS_QUEUE_OK"
    ;;
  *)
    echo "usage: $0 {add <text>|list|next|done <id>|check}" >&2
    exit 2
    ;;
esac
