#!/bin/sh
# Probe the technician's Sync Gateway grants: re-provision tech_garcia with
# per-collection channel access, then check reads (allowed), workorder writes
# (allowed) and station writes (admin-only, expect 403).
set -eu

ADMIN=http://localhost:4985
PUBLIC=http://localhost:4984
KS=fleetops._default

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "== 1. provision user =="
SG_ADMIN_URL="$ADMIN" sh "$(dirname "$0")/sg_setup.sh" tech_garcia password fleet

echo "== 2. stored grant =="
curl -s -u Administrator:password "$ADMIN/fleetops/_user/tech_garcia" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  collection_access:",json.dumps(d.get("collection_access")))'

echo "== 3. probe as tech_garcia =="
echo "  GET station doc            -> $(code -u tech_garcia:password "$PUBLIC/$KS.stations/station::EVSE-000") (expect 200)"
echo "  GET stations _all_docs     -> $(code -u tech_garcia:password "$PUBLIC/$KS.stations/_all_docs?limit=1") (expect 200)"
echo "  GET workorder doc          -> $(code -u tech_garcia:password "$PUBLIC/$KS.workorders/wo::sample-0") (expect 200)"
echo "  PUT station doc            -> $(code -u tech_garcia:password -X PUT "$PUBLIC/$KS.stations/probe-denied" \
  -H 'Content-Type: application/json' -d '{"type":"station"}') (expect 403)"
