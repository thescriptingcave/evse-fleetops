# EVSE FleetOps

Offline service & telemetry platform for EV charging-network operators.

- **Dashboard** — React + TypeScript + Tailwind + Recharts (Vite)
- **Backend** — Python FastAPI REST API + Server-Sent Events live feed
- **Simulator** — Python telemetry emitter (status, meters, temp/humidity/vibration, sessions)
- **Data platform** — Couchbase Server (Docker), Couchbase App Services / Sync Gateway
- **Mobile** — React Native (Expo) technician app on Couchbase Lite (scaffold, see [docs/mobile-status.md](docs/mobile-status.md))

## Documentation

| Doc | What's in it |
| --- | --- |
| [Getting started](docs/getting-started.md) | Prerequisites, first run, common tasks, troubleshooting |
| [Architecture](docs/architecture.md) | Components, topology, data model, API, security posture |
| [Design](docs/design.md) | Key decisions and trade-offs, configuration, known limitations |
| [Data flow](docs/data-flow.md) | Ingest, sessions, live updates, overrides, work order sync, provisioning |
| [Verification](docs/verification.md) | What is and isn't verified, and how to set up this machine to verify the rest |
| [Gotchas](docs/gotchas.md) | Side effects of the 2026-09-23 session and built-in traps |
| [Mobile status](docs/mobile-status.md) | Technician app status and roadmap |

## Architecture

```
simulator ──REST batch──▶ FastAPI ──couchbase──▶ Couchbase Server
dashboard ◀──SSE──────────┤                        │
                          └──REST /api/**──▶      │
technician app ◀─▶ Sync Gateway ◀─▶ Couchbase Server (bidirectional, delta sync)
```

Couchbase documents live in one bucket (`fleetops`) with six collections:
`stations`, `telemetry` (7-day TTL), `sessions`, `workorders`, `manuals`, `technicians`.
Sync Gateway replicates `stations`, `workorders`, `manuals` and `technicians` to
Couchbase Lite on the technician devices, so work orders and notes work
fully offline and reconcile automatically via conflict resolution.

## Quickstart

Prereqs: Docker, `uv`, Node 20+.

```bash
# 1. Start Couchbase Server + Sync Gateway (via Docker)
make up

# 2. Provision schema (bucket, collections, indexes) and seed 12 stations + manuals
make bootstrap

# 3. Create a Sync Gateway user for the technician app (channel: fleet)
make sg-user

# 4. Run the backend API  (http://localhost:8010, /docs for OpenAPI)
#    Override with `make backend sim API_PORT=...`; the dashboard proxy reads EVSE_API_URL.
make backend

# 5. In another terminal, stream telemetry
make sim

# 6. In another terminal, start the dashboard  (http://localhost:5173)
make dashboard
```

Or run a scripted end-to-end demo: `make demo`.

## Tests

```bash
make test          # backend + simulator (needs Couchbase running + bootstrapped)
make test-backend
make test-sim
make build-dashboard   # typecheck + production build of the dashboard
```

## API surface

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/telemetry/batch` | Simulator ingest (samples + session events) |
| GET | `/api/telemetry/latest` | Latest reading per station (poll fallback) |
| GET | `/api/events/stream` | Server-Sent Events: `telemetry`, `status`, `session`, `alert`, `workorder`, `snapshot` |
| GET | `/api/fleet/overview` | KPI aggregates |
| GET | `/api/stations` · `/api/stations/{serial}` | Station master data |
| GET | `/api/stations/{serial}/timeseries?metric=&bucket_minutes=` | Windowed N1QL aggregation |
| PATCH | `/api/stations/{serial}` | Operator status override |
| GET | `/api/sessions` · `/api/sessions/active` | Charging sessions |
| GET/POST/PUT | `/api/workorders` · `/api/workorders/{id}` | Maintenance work orders |
| POST | `/api/workorders/{id}/notes` | Technician notes |
| GET | `/api/manuals` | Manuals (synced to mobile) |

## Credentials (local dev)

- Couchbase console: `Administrator` / `password`
- Sync Gateway Couchbase Lite user: `tech_garcia` / `password` (channel `fleet`)

## Editing data model / collections

`backend/app/bootstrap.py` owns schema + seed. Indexes are created idempotently
on startup (`EVSE_BOOTSTRAP_ON_STARTUP`) and via `make bootstrap`.