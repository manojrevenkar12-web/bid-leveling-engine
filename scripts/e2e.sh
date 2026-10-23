#!/usr/bin/env bash
# End to end: platform API + AI service, publish a leveled tender, review a finding, ask a question.
# Needs DATABASE_URL, a built platform (platform/dist) and reports/runs/<tender>.json from `ble run`.
set -euo pipefail
T=${1:-T51}
cd "$(dirname "$0")/.."
export PLATFORM_API_KEYS="e2e-worker:worker,e2e-reviewer:reviewer"
(cd platform && PORT=3100 node dist/server.js > /tmp/ble-platform.log 2>&1 &)
BLE_PLATFORM_URL=http://127.0.0.1:3100 BLE_PLATFORM_KEY=e2e-reviewer ble serve --port 8101 > /tmp/ble-ai.log 2>&1 &
export AI=http://127.0.0.1:8101
for i in $(seq 1 40); do curl -sf localhost:3100/health >/dev/null && curl -sf $AI/health >/dev/null && break; sleep 0.5; done
ble publish "reports/runs/$T.json" --api http://127.0.0.1:3100 --key e2e-worker
H=(-H "x-api-key: e2e-reviewer" -H "content-type: application/json")
curl -sf "${H[@]}" "localhost:3100/api/tenders/$T/sheet" | python3 -c "import json,sys; s=json.load(sys.stdin); assert s['ranking'] and s['cells'], 'empty sheet'; print('sheet', len(s['cells']), 'positions')"
FID=$(curl -sf "${H[@]}" "localhost:3100/api/tenders/$T/findings" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
curl -sf "${H[@]}" -X POST "localhost:3100/api/findings/$FID/decision" -d '{"verdict":"confirmed","reviewer":"e2e"}' >/dev/null
curl -sf "${H[@]}" -X POST "localhost:3100/api/tenders/$T/chat" -d '{"question":"Who is cheapest?"}' | python3 -c "
import json,sys; a=json.load(sys.stdin); assert a['intent']=='ranking' and a['citations'] and a['dropped']==0, a; print(a['text'].splitlines()[0])"
DOC=$(python3 -c "
import json; r=json.load(open('reports/runs/$T.json'))
e=next(e for f in r['findings'] for e in f['evidence'] if e.get('page') and e['doc'].split('@')[0].endswith('.pdf'))
print(e['doc'] + ' ' + str(e['page']) + ' ' + ','.join(str(v) for v in e['bbox']))")
read -r D P B <<<"$DOC"
curl -sf -H "x-api-key: e2e-reviewer" -G "localhost:3100/api/evidence" --data-urlencode "doc=$D" --data-urlencode "page=$P" --data-urlencode "bbox=$B" -o /tmp/ble-evidence.png
python3 -c "assert open('/tmp/ble-evidence.png','rb').read(8)==b'\x89PNG\r\n\x1a\n'; print('evidence crop ok')"
curl -sf localhost:3100/metrics | grep -q 'ble_review_decisions_total' && echo "e2e passed"
