# Mobile (technician app) status & roadmap

## Status: scaffold — mock mode runs today, Couchbase Lite path is written but gated

The app uses **React Native (Expo SDK 54)** and the **official
`@couchbase/couchbase-lite-react-native` native module (v1.1, Couchbase Lite 3.3)**.

Couchbase Lite is a Swift/Kotlin native library bridged to JS via TurboModules.
That means it **cannot run in Expo Go** — it requires a native **dev-client**
build (`npx expo run:ios` / `run:android`). We cannot produce or run those
native builds from this CLI environment, so:

1. The app currently boots a **mock, in-memory store** (`src/store.ts`) that
   needs zero native deps and runs in Expo Go.
2. The **Couchbase Lite adapter is fully written** (`src/db/database.ts`):
   opening the local DB, scopes/collections, bidirectional continuous
   replication against Sync Gateway, delta sync, offline queued writes. It is
   imported only when `EXPO_PUBLIC_USE_COUCHBASE_LITE=1`.
3. Sync Gateway is configured to serve the document types the app reads/writes
   (see `sync-gateway/sg-config.json`).

## What runs today

```bash
cd mobile
npm install
npx expo start        # run in Expo Go (mock mode)
```

You get Stations, Work Orders (with offline note entry), and a Sync status
screen.

## Enabling real offline sync (requires a Mac for iOS / Android SDK)

1. Configure paths in `src/db/database.ts` /
   `.env` (`EXPO_PUBLIC_SG_URL`, `EXPO_PUBLIC_SG_USER`, `EXPO_PUBLIC_SG_PASSWORD`).
2. Set `EXPO_PUBLIC_USE_COUCHBASE_LITE=1`. The native module is linked by
   Expo autolinking during prebuild (no custom config plugin needed); check
   licensing/setup at [cbl-reactnative.dev](https://cbl-reactnative.dev).
3. Build a dev-client: `npx expo run:ios` (or `run:android`).
4. Point the simulators at the host: `EXPO_PUBLIC_SG_URL=ws://<host-ip>:4984/fleetops`
   (WebSocket scheme and database name required; not `localhost` — Android
   emulator uses `10.0.2.2`).
5. Test offline: create a note, toggle the device to airplane mode, close the
   app, reopen on network; the replicator replays queued writes, Couchbase
   Server applies last-write-wins conflict resolution, and the web dashboard
   shows the note.

## Version pins to verify at build time

| Dependency | Inherited | Notes |
| --- | --- | --- |
| `expo` | `~54.0.0` | RN 0.81, React 19.1, new architecture on |
| `@couchbase/couchbase-lite-react-native` | `^1.1.0` | Needs CBL 3.3.x iOS/Android SDK + new arch |
| `expo-dev-client` | `~6.0.21` | Local native development builds |

## Roadmap

- Real BLE/healthcheck field form (prefill station from QR scan)
- Manuals + attachments as Couchbase blobs
- Technician identity from `technicians` collection; channel-scoped sync roles
  (`technician.<username>` channels instead of a shared `fleet` channel)
- Custom conflict handlers on work orders (merge notes arrays)
- E2E sync test harness (`cblite` CLI vs Sync Gateway)