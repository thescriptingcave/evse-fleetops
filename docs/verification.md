# EVSE FleetOps — Verification Status

What has been checked, what hasn't, and how to set up this machine to check
the rest. Last updated 2026-09-23.

## Verified

| Area | How it was verified | Result |
| --- | --- | --- |
| Backend API | `make test-backend` (12 integration tests against local Couchbase) | pass |
| Simulator | `make test-sim` (7 tests, incl. offline buffering and ordering), run 20× in a row | pass, no flakes |
| Dashboard types and build | `npm run build` (`tsc -b` + `vite build`) | pass |
| Mobile types | `npx tsc --noEmit` | pass |
| Mobile JS bundle | `npx expo export --platform ios` (Metro bundles `App.tsx` → 1.7 MB Hermes bytecode) | pass |
| Backend + simulator end to end | Backend on `:8010`, simulator 20 ticks × 12 stations | 240 samples accepted, 0 dropped, no backend errors |
| SSE stream | `curl -N` on `/api/events/stream`, both directly and through the Vite proxy on `:5173` | `snapshot` first, then named `telemetry`/`status`/`session`/`alert` events |
| Session restore | Restarted the backend with 7 sessions active | "restored 7 active sessions"; DB and memory agree (7) |
| Alert de-duplication | Live run | 1 alert event while the condition held (was one per sample) |
| Operator override | Integration test `test_operator_override_survives_telemetry` | MAINTENANCE survives a CHARGING sample; AVAILABLE clears it |
| Bootstrap container | `docker compose up --build --no-deps bootstrap` with the updated Dockerfile (`--no-dev`) | `schema ok`, exit 0 |
| Sync Gateway provisioning | `docker compose up --no-deps sg-db-init` (existing-DB path) | `config updated`, user status 200 |
| Sync Gateway permissions | `scripts/sg-readgrant-probe.sh` as `tech_garcia` | reads 200, work order write 201, station write 403 |
| Mobile app UI in mock mode | `npx expo run:ios` on iPhone 16 Pro simulator (iOS 26.4.1, Xcode 26.4.1); screenshot confirms header "MOCK", 4 stations with correct status chips, Work Orders and Sync tabs present | pass |
| Couchbase Lite on iOS simulator | `EXPO_PUBLIC_USE_COUCHBASE_LITE=1 npx expo run:ios` on iPhone 16 Pro simulator; header shows "COUCHBASE-LITE", all 12 seeded stations pulled from Sync Gateway, Sync tab shows replicator: idle, progress: 100%, pending: 0, last sync timestamped | pass |
| Device → dashboard note sync | Added note "Testing .. testing .. testing" on Work Orders tab; appeared in backend API (`/api/workorders`) within seconds via Sync Gateway | pass |

## Not verified

Ordered by risk, highest first.

| # | Item | Why not | Risk |
| --- | --- | --- | --- |
| 1 | **Offline note sync**: add a note on device while offline, restore connectivity, confirm note appears in dashboard | Not yet exercised this session | Medium |
| 2 | **Dashboard → device sync**: create a work order via the API/dashboard, confirm it appears in the app | Not yet exercised this session | Low |
| 3 | **Dashboard in a browser**: rendering, charts, clicking through pages, operator buttons, work order create/notes | Checked only at the HTTP level (curl), not in a browser | Medium |
| 4 | **Fresh install from zero**: `make clean && make up` on an empty Docker volume (first-run `cb-init`, bucket creation, `sg-db-init` *create* path) | The existing cluster and volume were kept; only the re-run paths were exercised | Medium: the first-run code paths were not changed except in `sg-db-init.sh`'s user payload |
| 5 | **`make demo`** as a single command | Its parts (compose, bootstrap, backend, simulator `--duration`) were run separately | Low |
| 6 | **Real outage recovery**: kill the backend mid-run and bring it back with the simulator running | Covered by unit tests with a mocked HTTP transport only | Low |
| 7 | **Station write throttle** (60 s) and **TTL expiry** (7 days) under long runs | Runs were shorter than the intervals | Low |
| 8 | **Work order conflict** between the dashboard and a device editing the same document concurrently | Needs item 1 | Low (CAS logic is covered for the backend side) |

## Setting up this machine to verify the rest

This Mac has: Docker 29.7, `uv` 0.11, Node 24, Java 17 (Homebrew `openjdk@17`),
Xcode 26.4.1 (full app, license accepted), iOS 26.4.1 Simulator runtime,
CocoaPods 1.17, Watchman. Couchbase Server and Sync Gateway containers are running.

### For item 3: dashboard in a browser (5 minutes)

Nothing to install.

```bash
make backend                 # terminal 1
make sim                     # terminal 2
make dashboard               # terminal 3, then open http://localhost:5173
```

Checklist:

- [ ] Overview: KPI cards fill in; the event feed shows `telemetry`/`status`/`session` events within seconds; the pie chart shows the status mix.
- [ ] Stations: cards update live; clicking one shows the history chart (switch metric and bucket size).
- [ ] Click **Set MAINTENANCE** on a charging station → it stays MAINTENANCE while the simulator keeps running; **Set AVAILABLE** releases it.
- [ ] Work Orders: the table lists the 2 seeded orders; create one; add a note; change the status. No errors in the browser console.
- [ ] Stop the backend for 20 s and start it again → the feed reconnects by itself.

### For item 2: mobile mock mode (15 minutes)

Install **Expo Go** on an iPhone or Android phone on the same Wi-Fi network, then:

```bash
cd mobile && npx expo start   # scan the QR code with the phone's camera / Expo Go
```

Checklist: Stations tab lists 4 stations; Work Orders tab opens without
crashing; expanding the order and adding a note shows it immediately; Sync tab
shows "mock".

### For item 1: Couchbase Lite on iOS (about 1–2 hours, mostly downloads)

1. Install **Xcode** (full app, ~15 GB) from the App Store, then:
   ```bash
   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
   sudo xcodebuild -license accept
   xcodebuild -downloadPlatform iOS        # iOS simulator runtime
   ```
2. Install CocoaPods and Watchman:
   ```bash
   brew install cocoapods watchman
   ```
3. Build and run the dev client in the iOS simulator. The simulator shares the Mac's network, so `127.0.0.1` reaches Sync Gateway:
   ```bash
   cd mobile
   EXPO_PUBLIC_USE_COUCHBASE_LITE=1 npx expo run:ios
   ```
   This runs `expo prebuild`, which generates `mobile/ios/` (see [gotchas](gotchas.md)).

### For item 1: Couchbase Lite on Android (about 1 hour)

1. Install **Android Studio** (`brew install --cask android-studio`), open it once, and let it install the Android SDK, an emulator image (API 34+) and platform tools.
2. Add to `~/.zshrc`:
   ```bash
   export ANDROID_HOME="$HOME/Library/Android/sdk"
   export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
   export JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
   ```
3. Start an emulator from Android Studio's Device Manager, then:
   ```bash
   cd mobile
   EXPO_PUBLIC_USE_COUCHBASE_LITE=1 \
   EXPO_PUBLIC_SG_URL=ws://10.0.2.2:4984/fleetops \
   npx expo run:android
   ```
   The Android emulator reaches the host at `10.0.2.2`, not `127.0.0.1`.

### Checklist for item 1 (either platform)

With the backend running (`make backend`):

- [ ] The app header shows `couchbase-lite`; the Sync tab reaches `idle` with a "last sync" time.
- [ ] Stations tab shows all 12 seeded stations (pulled from Sync Gateway, not the 4 mock ones).
- [ ] Work Orders shows the same orders as the dashboard.
- [ ] Add a note on the device → it appears in the dashboard's Work Orders table within a few seconds.
- [ ] Add a note in the dashboard → it appears on the device.
- [ ] **Offline:** enable airplane mode (or `adb shell svc wifi disable` / stop Sync Gateway with `docker stop evse-sync-gateway`), add a note, close and reopen the app (the note is still there, "pending" > 0), restore connectivity → the note reaches the dashboard.
- [ ] **Conflict:** while the device is offline, add a note to the same order from the dashboard; reconnect. Record which notes survive (expected today: last write wins, so one side's note may be lost; see the design doc's known limitations).

If the app crashes at start with `TurboModuleRegistry.getEnforcing('CblDatabase') could not be found`,
the native module isn't linked. Check that `newArchEnabled` is `true` in
`app.json` and rebuild with `npx expo run:ios --no-build-cache`.

### For item 4: fresh install from zero (10 minutes, destructive)

`make clean` **deletes the Couchbase volume and all data**, plus both
virtualenvs, `dashboard/node_modules` and `dashboard/dist`.

```bash
make clean
make up          # wait until: docker compose ps shows sg-db-init "Exited (0)"
docker compose logs cb-init bootstrap sg-db-init | tail -40
sh scripts/sg-readgrant-probe.sh   # expect 200 / 200 / 200 / 403
make test
```

### For items 5–7

```bash
make demo                        # item 5: expect "Streaming telemetry for 30s..." and no errors
# item 6: run `make backend` and `make sim` in two terminals. Stop the backend
#   (Ctrl-C) for ~30 s, then start it again. The sim log should show
#   "telemetry push failed", then "flushed backlog; delivered N samples", with dropped=0.
```

For item 7, leave the simulator running for more than 2 minutes and check that
`last_seen` on a station document (Couchbase UI → Documents → `stations`)
advances about once a minute rather than every tick.
