#!/bin/sh
# One-shot: wait for Sync Gateway, then create the `fleetops` database from
# sg-db.json via the admin API (config stored in Couchbase, not the file).
set -eu

SG_HOST="${SG_HOST:-sync-gateway}"
ADMIN="http://${SG_HOST}:4985"
CONFIG="/etc/sg-db.json"

n=0
until curl -s -o /dev/null "$ADMIN/"; do
  n=$((n + 1))
  if [ "$n" -gt 60 ]; then
    echo "sg-db-init: timed out waiting for Sync Gateway" >&2
    exit 1
  fi
  sleep 2
done

# Idempotent: PUT 200 on create, 409 if database already exists; on 409 a POST
# merges sg-db.json into the stored config so sync-function edits are applied on
# re-runs. Trailing slash so SG's admin router treats it as full DB path.
#
# Sync Gateway transiently answers 500 with "unable to connect to a query node"
# right after `docker compose up` while Couchbase's N1QL/index services are still
# warming up, and leaves the DB in a state where every request returns 403. Retry
# until the DB is actually open instead of giving up on a single try.
create_or_merge_db() {
  code=$(curl -s -o /tmp/sgdb.out -w '%{http_code}' -u "Administrator:password" \
    -X PUT "$ADMIN/fleetops/" \
    -H 'Content-Type: application/json' \
    --data-binary @"$CONFIG")
  case "$code" in
    200|201) echo "sg-db-init: created database 'fleetops'"; return 0 ;;
    409|412) ;;
    *) return 1 ;;
  esac
  code=$(curl -s -o /tmp/sgdb.out -w '%{http_code}' -u "Administrator:password" \
    -X POST "$ADMIN/fleetops/_config" \
    -H 'Content-Type: application/json' \
    --data-binary @"$CONFIG")
  case "$code" in
    200|201) echo "sg-db-init: database 'fleetops' config updated"; return 0 ;;
    *) return 1 ;;
  esac
}

n=0
until create_or_merge_db; do
  n=$((n + 1))
  if [ "$n" -gt 45 ]; then
    echo "sg-db-init: database create still failing after $n tries" >&2
    echo "  last status $code: $(cat /tmp/sgdb.out)" >&2
    exit 1
  fi
  sleep 2
done

# Mobile technician user (idempotent: PUT upserts the local SG user).
echo "sg-db-init: provisioning SG user 'tech_garcia'"
# Channel grants are per collection (collection_access); top-level
# admin_channels would only cover the _default collection.
G='{"admin_channels":["fleet"]}'
curl -s -o /dev/null -w 'sg-db-init: user status %{http_code}\n' \
  -u "Administrator:password" -X PUT "$ADMIN/fleetops/_user/tech_garcia" \
  -H 'Content-Type: application/json' \
  -d '{"name":"tech_garcia","password":"password","collection_access":{"_default":{"stations":'"$G"',"workorders":'"$G"',"manuals":'"$G"',"technicians":'"$G"'}}}'
