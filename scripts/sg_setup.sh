#!/bin/bash
# Create a Sync Gateway user with access to the fleet channel.
# Enables a Couchbase Lite client to pull stations/workorders/manuals/technicians
# and to push local workorder edits back to the central bucket.
set -eu

SG_ADMIN_URL="${SG_ADMIN_URL:-http://localhost:4985}"
USER="${1:-tech_garcia}"
PASSWORD="${2:-password}"
CHANNELS="${3:-fleet}"
SG_ADMIN_USER="${SG_ADMIN_USER:-Administrator}"
SG_ADMIN_PASS="${SG_ADMIN_PASS:-password}"

# The admin API requires auth. Channel grants must be made per collection via
# collection_access: top-level admin_channels only cover the _default collection,
# so without this every read/push on stations, workorders, ... returns 403.
grant="{\"admin_channels\":[\"${CHANNELS}\"]}"
access="{\"_default\":{\"stations\":${grant},\"workorders\":${grant},\"manuals\":${grant},\"technicians\":${grant}}}"
curl -fsS -u "${SG_ADMIN_USER}:${SG_ADMIN_PASS}" -X PUT "${SG_ADMIN_URL}/fleetops/_user/${USER}" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"${USER}\",\"password\":\"${PASSWORD}\",\"collection_access\":${access}}"

echo "sync-gateway user '${USER}' created with channels: ${CHANNELS}"