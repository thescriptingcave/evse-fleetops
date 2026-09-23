# EVSE FleetOps — Architecture

EVSE FleetOps is an offline-capable service and telemetry platform for operators
of EV charging networks. Chargers stream telemetry to a central API, operators
watch the fleet live on a web dashboard, and field technicians work from a
mobile app that keeps functioning without connectivity.

Related documents:
[design](design.md) · [data flow](data-flow.md) · [getting started](getting-started.md) ·
[verification](verification.md) · [gotchas](gotchas.md) · [mobile status](mobile-status.md)

## Components

| Component | Tech | Location | Runs where |
| --- | --- | --- | --- |
| Backend API | Python 3.12/3.13, FastAPI, `couchbase` SDK (async), `sse-starlette` | `backend/` | Host, `uvicorn` on `:8010` |
| Telemetry simulator | Python, `httpx`, asyncio | `simulator/` | Host |
| Dashboard | React 19, TypeScript, Vite 6, Tailwind 4, Recharts | `dashboard/` | Host, Vite dev server on `:5173` |
| Technician app | React Native 0.81 / Expo SDK 54, Couchbase Lite (React Native SDK 1.1) | `mobile/` | Expo Go (mock mode) or native dev-client build |
| Couchbase Server | `couchbase/server:enterprise-8.0.3` | `docker-compose.yml` | Docker |
| Sync Gateway | `couchbase/sync-gateway:4.1.2-enterprise` | `docker-compose.yml`, `sync-gateway/` | Docker |
| One-shot initializers | `cb-init`, `bootstrap`, `sg-db-init` containers | `scripts/`, `backend/Dockerfile` | Docker (exit after running) |

## Topology

```
                     ┌──────────────────────── Docker network: evse-net ─────────────────────────┐
                     │                                                                            │
                     │   cb-init ──▶ Couchbase Server ◀── bootstrap (schema + seed)               │
                     │               :8091 REST/UI · :8093 query · :11210 KV                      │
                     │                  ▲         ▲                                               │
                     │                  │         │ shared bucket (XATTR import)                  │
                     │                  │   Sync Gateway :4984 public / :4985 admin ◀── sg-db-init │
                     └──────────────────┼──────────────────────────▲─────────────────────────────┘
                                        │ couchbase://localhost     │ WebSocket
                                        │                           │ ws://<host>:4984/fleetops
  Simulator ─POST /api/telemetry/batch─▶ FastAPI :8010              │
                                        │                      Technician app
  Dashboard :5173 ──(Vite proxy /api)─▶ ├─ REST /api/**         (Couchbase Lite,
      ▲                                 └─ SSE /api/events/stream  offline-first)
      └────────────── live events ──────────┘
```

The backend, simulator and dashboard run on the host and reach Couchbase
through the published ports. Only the initializers and Sync Gateway run inside
the Docker network.

## Data model

One bucket, `fleetops`, in the `_default` scope, with six collections:

| Collection | Document key | TTL | Synced to mobile | Writers |
| --- | --- | --- | --- | --- |
| `stations` | `station::<serial>` | — | yes (read-only) | backend (telemetry, operator status changes), bootstrap seed |
| `telemetry` | `telemetry::<serial>::<epochMs>` | 7 days (collection max expiry + per-doc expiry) | no | backend |
| `sessions` | `session::<uuid>` | — | no | backend |
| `workorders` | `wo::<id>` | — | yes (read/write) | backend API, technician app |
| `manuals` | `manual::<key>` | — | yes (read-only) | bootstrap seed |
| `technicians` | `tech::<username>` | — | yes (read-only) | bootstrap seed |

Indexes (created idempotently by bootstrap): a primary index per collection, plus
`stations(status)`, `telemetry(station_id, ts_ms)`, `telemetry(ts_ms)`,
`sessions(station_id, start_ts)`, `sessions(state, start_ts)` and
`workorders(status, priority)`.

## Backend structure

```
backend/app/
  main.py          FastAPI app, lifespan (bootstrap + connect with retry, restore sessions), CORS
  config.py        Settings (env prefix EVSE_), enum constants
  db.py            Store: async Couchbase wrapper (get/insert/upsert/mutate-with-CAS/query)
  bootstrap.py     Idempotent schema (bucket, collections, indexes) and seed data
  live.py          In-process EventBroker: SSE fan-out, latest-reading cache, alert state,
                   active sessions
  keys.py          Document key builders, timestamp helpers
  models.py        Pydantic request models (TelemetryBatch, WorkOrderCreate, ...)
  routers/
    telemetry.py   POST /batch ingest, session lifecycle, GET /latest
    stations.py    list/get, windowed timeseries, PATCH operator status
    sessions.py    list, active
    workorders.py  CRUD and notes (CAS-protected)
    fleet.py       KPI overview
    manuals.py     list
    events.py      SSE stream
```

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/telemetry/batch` | Ingest samples and session events |
| GET | `/api/telemetry/latest` | Latest reading per station (polling fallback) |
| GET | `/api/events/stream` | SSE stream of named events: `snapshot`, `telemetry`, `status`, `session`, `alert`, `workorder` |
| GET | `/api/fleet/overview` | Status totals, active sessions, alerts, kWh today |
| GET | `/api/stations`, `/api/stations/{serial}` | Station master data plus latest reading |
| GET | `/api/stations/{serial}/timeseries` | Bucketed average of one metric (`metric`, `bucket_minutes`, `from_ts`, `to_ts`) |
| PATCH | `/api/stations/{serial}` | Operator status override |
| GET | `/api/sessions`, `/api/sessions/active` | Charging sessions |
| GET/POST | `/api/workorders` | List / create work orders |
| GET/PUT | `/api/workorders/{id}` | Get / update a work order |
| POST | `/api/workorders/{id}/notes` | Append a technician note |
| GET | `/api/manuals` | Service manuals |
| GET | `/healthz` | Liveness |

OpenAPI docs: `http://localhost:8010/docs`.

## Mobile sync

Sync Gateway runs in shared-bucket mode: it imports documents the SDK writes
and replicates `stations`, `workorders`, `manuals` and `technicians` to
Couchbase Lite. The sync functions (`sync-gateway/sg-db.json`) put every
document in the `fleet` channel:

- `workorders`: `requireAccess('fleet')`, so technicians can read and write.
- `stations`, `manuals`, `technicians`: `requireAdmin()`, so they are read-only
  from devices. Documents written by the SDK still import, because import runs
  with admin rights.

The technician user `tech_garcia` gets `fleet` **per collection** through
`collection_access`. Top-level `admin_channels` would only cover the
`_default` collection. `scripts/sg-readgrant-probe.sh` checks the grants end to end.

Sync Gateway needs Couchbase Server **Enterprise** for this shared-bucket
setup. Without mobile sync, the rest of the platform would run on Community
edition.

## Failure behavior

| Failure | Behavior |
| --- | --- |
| Couchbase not ready at backend start | Bootstrap + connect retried 10 × 3 s, then startup fails with the last error |
| Backend unreachable from simulator | Samples and session events buffered (up to 500 samples, oldest dropped first), exponential backoff to 30 s, sent in order on reconnect |
| Backend rejects a batch as invalid (4xx) | Simulator discards it and logs the response instead of retrying forever |
| Backend restart | Active sessions are reloaded from Couchbase; the in-memory latest-reading cache and recent-event buffer start empty |
| SSE stream drops | Dashboard reconnects every 3 s and polls `/api/telemetry/latest` every 15 s while disconnected |
| Device offline | Couchbase Lite keeps working locally; the replicator pushes queued changes on reconnect |

## Security posture (local development only)

- Single Couchbase admin, `Administrator` / `password`, used by the backend, Sync Gateway and scripts.
- The API has no authentication. CORS allows only `localhost:5173`.
- The Sync Gateway admin API (`:4985`) is published on the host.
- The technician password is `password`.

None of this is suitable beyond a developer machine. Separate RBAC users for
the SDK, Sync Gateway and operators are a documented follow-up.
