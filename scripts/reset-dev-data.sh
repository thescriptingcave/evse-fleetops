#!/bin/sh
# Reset the local dev database to fresh seed data without touching Docker volumes,
# virtualenvs or node_modules (unlike `make clean`).
#
# Deletes every document in stations, telemetry, sessions and workorders, then
# re-runs bootstrap to re-seed the 12 stations and 2 sample work orders.
# Manuals and technicians are seed-only and are left as they are.
# Sync Gateway's `_sync:*` metadata docs are kept, or mobile sync would break.
set -eu

CB_QUERY="${CB_QUERY:-http://localhost:8093/query/service}"
CB_AUTH="${CB_AUTH:-Administrator:password}"
API_URL="${EVSE_API_URL:-http://localhost:8010}"

if curl -fs --max-time 2 "$API_URL/healthz" >/dev/null 2>&1; then
  echo "reset-dev-data: the backend is running at $API_URL; stop it (and the simulator) first." >&2
  echo "  Its in-memory state (active sessions, latest readings) would no longer match the database." >&2
  exit 1
fi

if [ "${1:-}" != "--yes" ]; then
  printf "Delete ALL stations, telemetry, sessions and work orders in the local fleetops bucket? [y/N] "
  if ! read -r answer; then
    echo
    echo "reset-dev-data: no answer (not an interactive terminal). Re-run with --yes, or: make reset-data YES=1" >&2
    exit 1
  fi
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "aborted"; exit 1; }
fi

for coll in telemetry sessions workorders stations; do
  printf "reset-dev-data: %-11s " "$coll"
  curl -fsS -u "$CB_AUTH" "$CB_QUERY" \
    --data-urlencode "statement=DELETE FROM \`fleetops\`.\`_default\`.\`$coll\` d WHERE META(d).id NOT LIKE '_sync:%'" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["status"], d.get("metrics",{}).get("mutationCount",0), "deleted")'
done

echo "reset-dev-data: re-seeding"
cd "$(dirname "$0")/../backend" && uv run python ../scripts/bootstrap.py
echo "reset-dev-data: done"
