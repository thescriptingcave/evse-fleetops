#!/bin/sh
# One-shot, idempotent single-node Couchbase Server bootstrap via REST.
# Creates services, memory quotas and the admin credentials used throughout EVSE FleetOps.
set -eu

HOST="${CB_HOST:-couchbase-server}"
BASE="http://${HOST}:8091"
ADMIN_USER="${CB_ADMIN_USER:-Administrator}"
ADMIN_PASS="${CB_ADMIN_PASS:-password}"

wait_for_server() {
  n=0
  # Any HTTP status (= curl exit 0) counts as reachable; 401 after
  # initialization must not be mistaken for the server being down.
  until curl -s -o /dev/null "$BASE/pools"; do
    n=$((n + 1))
    if [ "$n" -gt 60 ]; then
      echo "cb-init: timed out waiting for Couchbase Server" >&2
      exit 1
    fi
    sleep 2
  done
}

# Already initialized once admin credentials are set: /settings/web then
# requires authentication and returns 401 without it (before setup it is 200).
already_initialized() {
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/settings/web")" = "401" ]
}

wait_for_server

if already_initialized; then
  echo "cb-init: cluster already initialized, nothing to do"
  exit 0
fi

echo "cb-init: enabling kv, n1ql, index services"
curl -fsS -X POST "$BASE/node/controller/setupServices" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'services=kv,n1ql,index'

echo "cb-init: setting memory quotas"
curl -fsS -X POST "$BASE/pools/default" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'memoryQuota=512&indexMemoryQuota=256'

echo "cb-init: setting indexer storage mode"
curl -fsS -X POST "$BASE/settings/indexes" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'storageMode=memory_optimized&indexerThreads=0&logLevel=info'

echo "cb-init: setting admin credentials"
curl -fsS -X POST "$BASE/settings/web" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "username=${ADMIN_USER}" \
  --data-urlencode "password=${ADMIN_PASS}" \
  --data 'port=SAME'

echo "cb-init: done"