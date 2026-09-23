# EVSE FleetOps — Design

This document explains *why* the system is built the way it is: the key
decisions, the trade-offs they carry, and the rules each component follows.
For *what* the parts are, see [architecture](architecture.md); for how data
moves, see [data flow](data-flow.md).

## Goals

1. **Live fleet visibility.** Operators see status, sensor readings, sessions and alerts within seconds.
2. **Offline field work.** Technicians can read stations and manuals and update work orders with no connectivity; changes sync when they reconnect.
3. **Tolerant ingest.** Chargers on flaky links must not lose data during outages or corrupt live state when they catch up.
4. **Runs on one laptop.** Everything starts with Docker plus `uv` and `npm`.

Non-goals for now: multi-tenant auth, horizontal scaling of the API, production hardening.

## Key decisions

### 1. Couchbase + Sync Gateway as the single data platform

The same bucket serves the backend (SDK and SQL++ queries) and the mobile app
(Couchbase Lite through Sync Gateway). This avoids a second sync system and
gives offline replication, conflict handling and delta sync without custom
code.

- **Cost:** Sync Gateway's shared-bucket mode needs Couchbase **Enterprise**.
- **Cost:** the backend and Sync Gateway both write to `workorders`, so the backend must use CAS (see decision 5).

### 2. One document per telemetry sample, with a TTL

Telemetry goes to its own collection as `telemetry::<serial>::<epochMs>`, with a
7-day expiry. Charts are computed on demand with a SQL++ `GROUP BY
FLOOR(ts_ms / bucket)` over the `(station_id, ts_ms)` index.

- Simple and idempotent: replaying a sample overwrites the same key.
- **Trade-off:** there are no pre-aggregated rollups, so long windows at fine granularity cost more query time. That's fine for 12 stations × 7 days.

### 3. In-process event broker and SSE, not a message bus

`app/live.py` holds an `EventBroker` in memory. It fans events out to SSE
subscribers (bounded queue of 512 each; a slow consumer drops events rather
than blocking ingest). It also keeps the latest reading per station, the last
200 events, current alert state and active sessions.

- **Why:** no extra infrastructure, sub-second latency, trivially simple.
- **Constraint:** the backend must run as **one process**. Several uvicorn workers would each have their own broker, and clients would see partial streams.
- **Durability rule:** anything that must survive a restart is also in Couchbase. Active sessions are reloaded at startup (`load_active_sessions`). The latest-reading cache rebuilds from the next sample; recent events are lost by design.

SSE events are **named** (`event: telemetry`, etc.), so clients must use
`addEventListener(name)`, not `onmessage`.

### 4. Station documents: master data plus throttled live state

Station documents replicate to every technician device, so writing one on every
sample (every 5 s) would flood mobile sync. The rule is:

- Write the station document only when the reported status changes, or at most once per 60 s (`STATION_WRITE_INTERVAL_S`).
- Push live readings to the dashboard over SSE from the in-memory cache, not from the document.
- Ignore late samples (older than the station's latest) for live state. They are still stored as telemetry for history.

### 5. Optimistic concurrency (CAS) for shared documents

`Store.mutate(collection, key, fn)` does get → apply `fn` → `replace` with CAS,
and retries on `CasMismatchException` (up to 8 times). Every read-modify-write
of a document that another writer can touch uses it: work order updates and
notes, operator status changes, and telemetry updates to stations. Blind
`upsert` is only used for documents the backend alone owns (telemetry,
sessions, new work orders).

### 6. Operator overrides beat device-reported status

`PATCH /api/stations/{serial}` with any status other than `AVAILABLE` stores
`operator_status` on the station. While it's set, telemetry updates the
readings but keeps the operator's status. Setting `AVAILABLE` clears the
override and hands control back to the charger.

### 7. Edge-triggered alerts

Thresholds (`app/live.py`): temperature ≥ 55 °C, vibration ≥ 12 mm/s, humidity ≥ 90 %.
An `alert` event fires only when a *kind* of alert becomes active for a
station, not on every sample while it stays active. `/api/fleet/overview`
reports the currently active set, including FAULTED/OFFLINE stations.

### 8. Session lifecycle is event-driven and self-healing

- `start` creates `session::<id>` as `ACTIVE` and registers it in memory.
- `end` completes it, using the reported `kwh` or, if that's missing, end meter minus start meter.
- A `start` on a station that already has an active session marks the old one `ABANDONED`, because its end event was lost.
- An `end` with no session in memory falls back to looking up `session_id` in Couchbase.

### 9. Simulator transport is ordered, bounded and poison-safe

The simulator keeps one pending list of samples and one of session events. Each
tick it appends the new data and sends *everything pending* in one request, so
the backend always receives data oldest-first.

- On network errors, 5xx and 404/408/425/429 it keeps the data and backs off exponentially (1 s up to 30 s).
- On any other 4xx it discards the data. A malformed batch would otherwise block the queue forever.
- It holds at most 500 samples and drops the oldest first. Session events are never trimmed.

### 10. Mobile app: one store interface, two backends

`FleetStore` (`mobile/src/store.ts`) has a mock in-memory implementation and a
Couchbase Lite one (`mobile/src/db/database.ts`). The flag
`EXPO_PUBLIC_USE_COUCHBASE_LITE=1` picks between them, so the UI runs in Expo
Go without native code. Work orders created on a device use `wo::` keys so the
backend API can address them.

### 11. Idempotent provisioning everywhere

Bucket, collections, indexes, seed data, Sync Gateway database and users can
all be re-applied safely. Bootstrap runs from the compose `bootstrap`
container, from `make bootstrap`, and on every backend start
(`EVSE_BOOTSTRAP_ON_STARTUP`, default `true`). `sg-db-init.sh` updates the
Sync Gateway config if the database already exists, instead of skipping it.

## Configuration

Backend settings (`backend/app/config.py`, prefix `EVSE_`, also read from `backend/.env`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `EVSE_CB_HOST` | `localhost` | Couchbase host |
| `EVSE_CB_USERNAME` / `EVSE_CB_PASSWORD` | `Administrator` / `password` | Couchbase credentials |
| `EVSE_BUCKET` / `EVSE_SCOPE` | `fleetops` / `_default` | Keyspace (SQL++ statements hard-code `fleetops`._default) |
| `EVSE_BOOTSTRAP_ON_STARTUP` | `true` | Provision schema on backend start |
| `EVSE_SEED_ON_STARTUP` | `true` | Insert seed data if missing |
| `EVSE_TELEMETRY_TTL_DAYS` | `7` | Telemetry expiry |

Other knobs:

| Where | Variable | Default |
| --- | --- | --- |
| Makefile | `API_PORT` | `8010` |
| Makefile, simulator, dashboard proxy | `EVSE_API_URL` | `http://localhost:$(API_PORT)` |
| Mobile | `EXPO_PUBLIC_USE_COUCHBASE_LITE` | unset (mock mode) |
| Mobile | `EXPO_PUBLIC_SG_URL` | `ws://127.0.0.1:4984/fleetops` |
| Mobile | `EXPO_PUBLIC_SG_USER` / `EXPO_PUBLIC_SG_PASSWORD` | `tech_garcia` / `password` |

## Known limitations and follow-ups

- **Single process.** The event broker is in-process; scaling out needs a shared bus (e.g. Redis pub/sub or Couchbase eventing).
- **No auth** on the API or dashboard; one shared Couchbase admin. RBAC is a follow-up.
- **Hard-coded keyspace** in SQL++ strings. Changing `EVSE_BUCKET` alone won't work.
- **Last-write-wins on devices.** Two technicians appending notes to the same work order offline can lose one note when the conflict resolves. A custom conflict resolver that merges `notes` arrays is planned.
- **Shared `fleet` channel.** Every technician sees every document. Per-technician channels are planned.
- **Connector enum is duplicated** in the simulator and backend. A simulator test guards it.
- **Mobile types are copied** from the dashboard by hand.
