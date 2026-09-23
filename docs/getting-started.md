# EVSE FleetOps — Getting Started

From a clean checkout to a live dashboard in about 10 minutes.

## 1. Prerequisites

| Tool | Version used | Install (macOS) |
| --- | --- | --- |
| Docker Desktop (or compatible) | 29.x, with ≥ 4 GB RAM for Docker | docker.com |
| `uv` (Python toolchain) | 0.11+ | `brew install uv` |
| Node.js | 20+ (tested on 24) | `brew install node` |
| `curl` | any | preinstalled |

Python itself is managed by `uv` (3.12 or 3.13). You don't need a system Python.

**Before you start:** make sure ports **8091, 8093, 8094, 11210, 4984, 4985,
8010 and 5173** are free. On this machine, port 8000 is used by another app
(oMLX), which is why the backend uses **8010**. See [gotchas](gotchas.md).

```bash
lsof -iTCP -sTCP:LISTEN -P | grep -E ':(8091|8093|8094|11210|4984|4985|8010|5173)\b'
```

## 2. Start the data platform

```bash
make up
```

This starts Couchbase Server and Sync Gateway, then runs three one-shot
containers in order: `cb-init` (cluster setup), `bootstrap` (bucket,
collections, indexes, seed data) and `sg-db-init` (Sync Gateway database and
the `tech_garcia` user). The first run takes 1–3 minutes.

Check it finished:

```bash
docker compose ps -a
# couchbase-server, sync-gateway: Up (healthy)
# cb-init, bootstrap, sg-db-init: Exited (0)
```

Couchbase console: http://localhost:8091 (`Administrator` / `password`).

`make bootstrap` and `make sg-user` re-apply the schema and the Sync Gateway
user by hand. Both are safe to repeat, and `make up` already runs them.

## 3. Run the apps (three terminals)

```bash
make backend      # FastAPI on http://localhost:8010  (OpenAPI docs: /docs)
make sim          # telemetry for 12 stations every 5 s
make dashboard    # http://localhost:5173
```

The first `make backend` / `make sim` creates each project's `.venv`. Run
`cd dashboard && npm install` once before the first `make dashboard`.

Start them **in this order**. The simulator looks up the station list from the
backend when it starts. If the backend isn't up yet, it logs a warning,
falls back to its built-in list of 12 stations, and keeps its readings in a
buffer until the backend appears.

Open http://localhost:5173. The Overview event feed should start moving within
a few seconds.

### Check the simulator is working

1. The backend answers: `curl localhost:8010/healthz` returns `{"status":"ok","couchbase":true}`.
2. The simulator logs a progress line every 10 ticks (about every 50 s at the default 5 s interval):
   ```
   INFO evse.sim: tick 10: charging=7/12, meters total ~29199 kWh, buffered=0, dropped=0
   ```
   `buffered=0, dropped=0` means every reading reached the backend. Between progress
   lines you'll see `session start on EVSE-00x` / `session end on EVSE-00x (n kWh)`.
3. For a quick test, run it faster and stop it by itself:
   ```bash
   cd simulator && uv run python -m sim --interval 1 --duration 15
   # ends with: duration reached after 15 ticks (180 samples delivered)
   ```
4. The data arrives: `curl localhost:8010/api/fleet/overview` shows `last_updated`
   within the last few seconds and a non-zero `active_sessions`.

The backend may log `session … abandoned (no end event)` warnings. These are
harmless: stopping the simulator leaves sessions open, and the backend closes
them when a new session starts on the same station.

Or run everything scripted for 30 seconds: `make demo`.

## 4. Run the tests

```bash
make test              # backend (needs Couchbase up) + simulator
make build-dashboard   # dashboard typecheck + production build
cd mobile && npm install && npx tsc --noEmit   # mobile typecheck
```

Backend tests write test sessions and work orders into your local database
(see [gotchas](gotchas.md)).

## 5. Mobile app (optional)

Mock mode (no native build, no sync):

```bash
cd mobile && npm install && npx expo start    # open with Expo Go on your phone
```

Real offline sync through Couchbase Lite needs a native build; see
[verification](verification.md#setting-up-this-machine-to-verify-the-rest) and
[mobile status](mobile-status.md).

## Common tasks

| Task | Command |
| --- | --- |
| Use a different API port | Pass the same value to each target: `make backend API_PORT=8020`, `make sim API_PORT=8020`, `make dashboard API_PORT=8020` |
| Faster simulation | `cd simulator && uv run python -m sim --interval 1 --speed 300` |
| Reproducible simulation | `... python -m sim --seed 42` |
| Simulate without sessions | `... python -m sim --no-sessions` |
| Stop after N seconds | `... python -m sim --duration 60` |
| Container logs | `make logs` |
| Stop containers (keep data) | `make down` |
| Reset data to fresh seed (keeps volumes, venvs, node_modules) | Stop the backend and simulator, then `make reset-data` (add `YES=1` to skip the prompt, e.g. from Claude Code's `!` prompt) |
| Wipe everything | `make clean` (**deletes all Couchbase data**, venvs, `dashboard/node_modules`, `dashboard/dist`) |
| Check Sync Gateway grants | `sh scripts/sg-readgrant-probe.sh` |

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Simulator logs `station discovery got HTTP 404` or `batch rejected status=404` | Something else is listening on the API port | Check `lsof -iTCP:8010 -sTCP:LISTEN`; change `API_PORT` |
| Simulator logs `telemetry push failed (offline?)` / `station discovery failed`, and `buffered=` keeps growing | The backend isn't running | `make backend`; the simulator sends its buffered readings in order once the backend answers, as long as fewer than 500 have piled up |
| Simulator logs `dropped=N` with N > 0 | The backend was down long enough to fill the 500-reading buffer; the oldest readings were discarded | Expected after long outages; start the backend first next time |
| `make backend`: `address already in use` | Another app on the API port, or an old backend still running | `kill $(lsof -tiTCP:8010 -sTCP:LISTEN)` |
| Backend logs `Couchbase not ready (attempt n/10)` then exits | Containers still starting, or `cb-init` failed | `docker compose ps -a`, `docker compose logs cb-init bootstrap` |
| Simulator logs `batch rejected status=422 ..., discarding` | Simulator and backend disagree on the payload (e.g. a new status or connector value) | Align `simulator/sim/fleet.py` with `backend/app/models.py` |
| Dashboard shows "Waiting for the stream…" forever | Backend not running, or the dashboard proxy points at the wrong port | Check that `EVSE_API_URL` matches the backend's port |
| Technician app / probe gets 403 on reads | User missing per-collection grants | `make sg-user` |
| `make sg-user` gets 401 | Wrong Sync Gateway admin credentials | Set `SG_ADMIN_USER` / `SG_ADMIN_PASS` |
