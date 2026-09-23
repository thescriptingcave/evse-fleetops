# EVSE Technician App — User Guide

How to use the iOS technician app once it is running on the Simulator or a
device. Last updated 2026-09-23.

## Overview

The technician app is a mobile companion to the EVSE FleetOps platform. It
gives field technicians a single screen for seeing station status, managing
work orders, and logging notes — all without needing a live connection.

There are two runtime modes:

| Mode | How to spot it | Data source |
|------|---------------|-------------|
| **mock** | Sync tab says "Storage mode: mock" | In-memory seed data; resets on restart |
| **couchbase-lite** | Sync tab says "Storage mode: couchbase-lite" | Local Couchbase Lite DB, syncs with Sync Gateway |

## Screens

### Stations tab

Lists every charging station visible to this technician.

| Field | Meaning |
|-------|---------|
| Name | Human-readable location label |
| Status chip | AVAILABLE · CHARGING · FAULTED · MAINTENANCE · OFFLINE |
| Serial | Unique station ID (e.g. EVSE-007) |
| Model | Hardware model (e.g. VoltHub DC 350) |
| Site type | parking / garage / remote |
| Firmware | Installed firmware version |

In mock mode you see 4 stations. In Couchbase Lite mode you see all 12 seeded
stations once the initial pull from Sync Gateway completes (usually within a
few seconds of the app starting).

### Work Orders tab

Lists open and in-progress work orders assigned to this technician. Tap a card
to expand it.

**Expanded card shows:**
- All previous notes (author, timestamp, text)
- A text field to add a new offline note

**Adding a note:**
1. Tap a work order card to expand it.
2. Type a note in the text field at the bottom of the card.
3. Tap **Add** or press Return.

In mock mode the note is added to in-memory state immediately and disappears on
restart. In Couchbase Lite mode the note is written to the local database first
and queued for sync — it persists across restarts even without connectivity.

### Sync tab

Shows the current sync state. Useful for checking connectivity and diagnosing
replication lag.

| Field | Values | Meaning |
|-------|--------|---------|
| Storage mode | mock / couchbase-lite | Which backend is active |
| Replicator | stopped / offline / connecting / idle / active | Sync Gateway connection state |
| Progress | 0–100% | How far through the current sync batch |
| Pending | integer | Documents queued for upload |
| Last sync | ISO timestamp / never | When the replicator last reached idle |

**Idle** is the steady state — it means all local changes have been pushed and
the latest remote changes have been pulled. The replicator runs continuously in
the background; you do not need to trigger sync manually.

## Offline workflow

The app is designed for intermittent connectivity.

1. Work while offline — add notes, view existing work orders and stations.
   All writes go to the local Couchbase Lite database instantly.
2. When connectivity returns the replicator automatically pushes queued
   changes to Sync Gateway and pulls any updates from other technicians or
   the web dashboard.
3. The Sync tab shows **Pending > 0** while documents are waiting to upload
   and **Replicator: active** while the sync is in progress.

**To simulate offline in the Simulator:** toggle the host Mac's Wi-Fi or run
`docker stop evse-sync-gateway`. The replicator will transition to `offline` on
the Sync tab. Restore connectivity and it reconnects automatically.

## Conflict resolution

If the same work order is edited on two devices (or on a device and the web
dashboard) while both are offline, the last write wins when they reconnect. One
side's notes may be overwritten. This is a known limitation; a merge-based
conflict resolver is on the roadmap.

## Verifying end-to-end sync

### Device → dashboard

1. Add a note to any work order in the app.
2. Wait for the Sync tab to show **Replicator: idle**.
3. Open the web dashboard Work Orders page — the note should appear within
   a few seconds.

### Dashboard → device

1. Create or update a work order via the dashboard (or the backend API):
   ```bash
   curl -s -X POST http://localhost:8010/api/work-orders \
     -H 'Content-Type: application/json' \
     -d '{"station_id":"EVSE-001","title":"Cable inspection","priority":"LOW"}'
   ```
2. The new order should appear on the app's Work Orders tab within the next
   poll cycle (up to 5 seconds).

## Credentials

The default technician account used by the app is `tech_garcia` / `password`.
This account has read access to stations, manuals and technicians, and
read/write access to work orders. It cannot write to stations or manuals (403).

To change credentials before building, set these environment variables:

```bash
EXPO_PUBLIC_SG_USER=tech_garcia
EXPO_PUBLIC_SG_PASSWORD=password
```

## Known limitations

- **No authentication UI** — credentials are hard-coded via env vars or the
  default values in `mobile/src/db/database.ts:16–17`.
- **Author is always `tech_garcia`** — the author field on notes is hard-coded
  in `Screens.tsx:91` pending a real login screen.
- **No work order creation UI** — new work orders can only be created via the
  backend API or the web dashboard.
- **Conflict resolution is last-write-wins** — concurrent offline edits to the
  same document can lose one side's changes.
- **Mock store resets on restart** — any notes added in mock mode are gone when
  the app is restarted. This is intentional; it's seed data for UI testing only.
