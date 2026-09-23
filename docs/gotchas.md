# EVSE FleetOps — Gotchas and Side Effects

Part 1 lists what the 2026-09-23 fix-and-verify session changed on this
machine beyond the source code. Part 2 lists traps that are built into how the
system works.

## Part 1: side effects of the 2026-09-23 session

### There is no version control

The project folder is **not a git repository**. None of the code changes from
this session can be diffed or reverted with git. Before making more changes:

```bash
git init && git add -A && git commit -m "Baseline after 2026-09-23 fixes"
```

Add a `.gitignore` first so these generated folders stay out of the commit:
`node_modules/`, `dist/`, `.venv/`, `__pycache__/`, `.pytest_cache/`,
`.ruff_cache/`, `*.tsbuildinfo`, `.demo-backend.log`, `mobile/ios/`,
`mobile/android/`, `mobile/.expo/`.

### Changes to the running Sync Gateway (live, not only in files)

| Change | Effect | Undo |
| --- | --- | --- |
| Sync functions replaced with `requireAdmin()` (stations, manuals, technicians) and `requireAccess('fleet')` (workorders) | Devices can no longer write stations/manuals/technicians (403). Work order writes still work. | Edit `sync-gateway/sg-db.json`, re-run `docker compose up --no-deps sg-db-init` |
| User `tech_garcia` re-created with per-collection grants (`collection_access`) | Replaces any grants set earlier; it previously had none that worked (all reads returned 403) | `make sg-user` re-applies the intended grants |
| Probe document `wo::sgprobe` created, deleted and **purged** | No trace left | — |

### Data written to the local Couchbase database (since reset)

Test and simulator runs during the session left test work orders, ~60
sessions, ~500 telemetry readings and a "test" status note on EVSE-005 in the
dev bucket. The bucket also held two junk station documents from before the
session ("Test Kiosk", "Probe Kiosk").

At the end of the session all of it was cleared with `make reset-data YES=1`
(520 telemetry, 63 sessions, 8 work orders and 14 station documents deleted),
and the seed data was restored. State afterwards:

| Collection | Contents |
| --- | --- |
| `stations` | 12 seeded stations, all AVAILABLE, no status notes |
| `workorders` | The 2 seeded sample work orders |
| `telemetry`, `sessions` | Empty |
| `manuals`, `technicians` | Unchanged seed data (4 manuals, 1 technician) |
| Every collection that syncs to phones | Sync Gateway's `_sync:syncInfo` document, kept on purpose |

The Sync Gateway grant check passed after the reset (reads 200, work order read
200, station write 403).

Running `make test` or the simulator again will add data again. Stop the backend
and simulator, then run `make reset-data` to clear it.

### Docker

- The `evse-fleetops-bootstrap` image was **rebuilt** (Dockerfile now runs `uv run --no-dev`).
- The `evse-bootstrap` and `evse-sg-db-init` containers were re-created and re-run. Both are idempotent and exited 0.
- Couchbase Server and Sync Gateway kept running; no volumes were touched.

### Files created, changed or deleted outside normal source edits

| Path | What happened |
| --- | --- |
| `dashboard/node_modules/`, `dashboard/package-lock.json` | Created by `npm install` (no lockfile existed before) |
| `dashboard/dist/`, `dashboard/tsconfig.tsbuildinfo` | Created by the production build |
| `mobile/node_modules/`, `mobile/package-lock.json` | Created by `npm install` |
| `mobile/plugin.config.js` | **Deleted**: unused, and its Android wiring was wrong. Expo autolinking handles the native module. |
| `mobile/tsconfig.json` | Now extends `expo/tsconfig.base` |
| `mobile/package.json` | `expo-dev-client` `~7.0.0` → `~6.0.21` (7.x doesn't exist) |
| `scripts/sg-readgrant-probe.sh` | Rewritten as a reusable grant check |

`npm install` warned that some packages' install scripts (e.g. `esbuild`'s
postinstall) weren't run automatically. The build still works; run
`npm install-scripts ls` to review them.

### Port change

The backend's default port moved from **8000 to 8010**, because another app
(`omlx-server`, an LLM inference server) owns 8000 on this machine. Anything
outside this repo that assumed `localhost:8000` for the EVSE API needs
updating. The oMLX process was not touched.

## Part 2: gotchas built into the system

### Running things

- **Port collisions fail quietly.** If another server answers on the API port, the simulator logs 404s and the dashboard stays empty, with no crash. Check `/healthz` returns `{"status":"ok","couchbase":true}`.
- **`make clean` is destructive.** It runs `docker compose down -v` (deletes the Couchbase volume and all data) and removes both `.venv`s, `dashboard/node_modules` and `dashboard/dist`.
- **Run the backend as a single process.** Live events, the latest-reading cache and alert state live in memory. `--workers N` would split them across processes. `--reload` is fine.
- **Backend startup re-seeds.** With `EVSE_SEED_ON_STARTUP=true` (default), deleted seed documents (stations, manuals, the two sample work orders, the technician) come back on the next backend start. Set it to `false` to stop that.
- **`make demo`** writes `.demo-backend.log` to the repo root and stops the backend when it exits.
- **Stopping the simulator leaves sessions ACTIVE and stations CHARGING.** It sends no "end" events on shutdown. The data corrects itself on the next run (old sessions become ABANDONED).

### Data behavior

- **Late samples don't update live state.** A sample older than the station's newest one is stored for history but ignored for the station document, SSE and alerts. A charger whose clock runs *ahead* will therefore mask correct samples that follow it until real time catches up.
- **Station documents update at most once a minute** unless the status changes. `last_seen` and sensor fields on the document can be up to 60 s stale; the dashboard's live values come from SSE.
- **Operator overrides stick.** A station set to MAINTENANCE (or any status except AVAILABLE) from the dashboard ignores the charger's reported status until someone sets AVAILABLE.
- **Alerts fire once per episode.** A temperature alert fires when the threshold is first crossed, not again until it clears and re-occurs.
- **Changing `EVSE_TELEMETRY_TTL_DAYS` doesn't change the existing collection.** The collection's max expiry is set only when bootstrap first creates it; new documents do get the new per-document expiry.
- **The keyspace is hard-coded** (`fleetops`._default) in SQL++ queries. Changing `EVSE_BUCKET`/`EVSE_SCOPE` alone won't work.
- **Tests write to your dev database** and need Couchbase running and bootstrapped. `make reset-data` clears what they leave behind.

### Sync Gateway

- **Grants are per collection.** Granting `admin_channels` at the top level of a user only covers the `_default` collection; reads on named collections return 403. Use `collection_access` (as `make sg-user` does).
- **The admin API needs credentials** (`Administrator` / `password`), and responds 401 without them.
- **REST paths use keyspace dots**, e.g. `/fleetops._default.stations/<docid>`, not `/fleetops/_default/stations/...` (that returns 404 "unknown URL").
- **The database config lives in Couchbase, not in the file.** Editing `sync-gateway/sg-db.json` does nothing until `sg-db-init` runs again (`docker compose up --no-deps sg-db-init` or `make up`).
- **Device conflicts are last-write-wins.** Two offline edits to the same work order can lose one side's notes.

### Dashboard

- **SSE events are named.** Any new client must use `addEventListener('telemetry', ...)` etc.; `onmessage` receives nothing.
- **The dev proxy target comes from `EVSE_API_URL`** at Vite start-up. Restart `make dashboard` after changing the port.

### Mobile

- **Couchbase Lite can't run in Expo Go.** Only use Expo Go in mock mode. With `EXPO_PUBLIC_USE_COUCHBASE_LITE=1` set, the app fails at start because the native module isn't there.
- **The sync URL must be `ws://…/fleetops`**: WebSocket scheme plus the database name. On the Android emulator the host is `10.0.2.2`; on a physical phone it's the Mac's LAN IP.
- **Couchbase Lite RN 1.1 needs the New Architecture** (`newArchEnabled: true` in `app.json`, already set). Otherwise the app crashes at start.
- **`expo run:ios` / `run:android` generate `mobile/ios/` and `mobile/android/`.** These are build output (prebuild); keep them out of version control or commit them deliberately.
- **Couchbase Lite, Sync Gateway and Couchbase Server are Enterprise editions.** Check Couchbase's license terms before any use beyond local development.
- **Mobile types are copied by hand** from the dashboard (`mobile/src/types.ts`). Keep them in sync when the model changes.

### macOS specifics

- There's no `timeout` command on macOS (it's GNU coreutils). Use the simulator's `--duration` flag.
- `sed -i` needs an empty suffix argument on macOS (`sed -i '' ...`).
