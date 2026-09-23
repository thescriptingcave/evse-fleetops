# Building the iOS Technician App

How to build and run the EVSE technician React Native app on an iOS Simulator.
Last updated 2026-09-23.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Xcode (full app) | 26.x | App Store |
| iOS Simulator platform | 26.4.1 | `xcodebuild -downloadPlatform iOS` |
| CocoaPods | 1.17+ | `brew install cocoapods` |
| Watchman | any | `brew install watchman` |
| Node | 20+ | Homebrew or nvm |
| uv | any | `brew install uv` |
| Docker | 29+ | Docker Desktop |

Verify these once before your first build:

```bash
xcode-select -p          # must print /Applications/Xcode.app/Contents/Developer
xcodebuild -version      # must print Xcode, not "error: tool requires Xcode"
pod --version
watchman --version
node --version
uv --version
docker --version
```

### Xcode license (one-time, requires sudo)

If `xcodebuild -version` fails with a license error:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
```

### iOS Simulator platform

Xcode ships the SDK but not the Simulator runtime. Download it once (8.5 GB):

```bash
xcodebuild -downloadPlatform iOS
```

This can run unattended. When it finishes,
`xcrun simctl list runtimes` should show `iOS 26.x`.

## Step 1 — Start the backend stack

The app needs Couchbase Server, Sync Gateway and the backend API running locally.

```bash
make up       # starts Docker containers; waits for health-checks
make test     # 19 tests should pass before you try the app
```

## Step 2 — Install JS dependencies

```bash
cd mobile
npm ci
```

## Step 3 — Mock mode (no native Couchbase Lite)

Builds a native Expo dev-client with the in-memory mock store. No Sync Gateway
replication; all data is seed data. This is the right first target on a new machine.

```bash
cd mobile
npx expo run:ios
```

Expo will:
1. Run `expo prebuild` — generates `mobile/ios/` from `app.json`.
2. Run `pod install` in `mobile/ios/`.
3. Compile the Xcode project and launch the Simulator.
4. Start the Metro bundler and load the JS bundle.

The `mobile/ios/` directory is build output — keep it out of version control (it
is listed in `.gitignore`).

### First build vs subsequent builds

The first build compiles all native modules and takes several minutes. Subsequent
builds are incremental and much faster. If you change `app.json` or add/remove
native packages, delete `mobile/ios/` and rebuild:

```bash
rm -rf mobile/ios && cd mobile && npx expo run:ios
```

### Choosing a specific simulator

```bash
npx expo run:ios --device "iPhone 16 Pro"
```

Run `xcrun simctl list devices available` to see what's installed.

### Taking a screenshot

```bash
xcrun simctl io booted screenshot ~/Desktop/evse-mock.png
```

## Step 4 — Couchbase Lite mode (full offline sync)

Enables the native Couchbase Lite database and bidirectional replication with
Sync Gateway. Requires the backend stack to be running (`make up`).

```bash
cd mobile
EXPO_PUBLIC_USE_COUCHBASE_LITE=1 npx expo run:ios
```

The app generates a unique `id` prefix `wo::` for new work orders so the backend
API can address them by key. The default Sync Gateway URL and credentials are:

| Variable | Default |
|----------|---------|
| `EXPO_PUBLIC_SG_URL` | `ws://127.0.0.1:4984/fleetops` |
| `EXPO_PUBLIC_SG_USER` | `tech_garcia` |
| `EXPO_PUBLIC_SG_PASSWORD` | `password` |

Override any of these on the command line or in a `.env` file in `mobile/`.

### Android emulator URL

The Android emulator's virtual network routes host traffic through `10.0.2.2`,
not `127.0.0.1`. Pass this when running `expo run:android`:

```bash
EXPO_PUBLIC_USE_COUCHBASE_LITE=1 \
EXPO_PUBLIC_SG_URL=ws://10.0.2.2:4984/fleetops \
npx expo run:android
```

### Force a clean native rebuild

If you hit odd linker or module errors:

```bash
rm -rf mobile/ios mobile/android
cd mobile && npx expo run:ios --no-build-cache
```

## Troubleshooting

### `TurboModuleRegistry.getEnforcing('CblDatabase') could not be found`

The native Couchbase Lite module wasn't linked. Check that `newArchEnabled: true`
is set in `app.json` (it is by default) and rebuild without the cache:

```bash
npx expo run:ios --no-build-cache
```

### `iOS 26.x is not installed`

The Simulator platform hasn't been downloaded for this Xcode version:

```bash
xcodebuild -downloadPlatform iOS
```

### `xcodebuild: error: tool requires Xcode`

`xcode-select` is pointing at Command Line Tools instead of the full app:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

### `pod install` hangs or fails

CocoaPods fetches specs from GitHub. If it stalls, check your network, then:

```bash
cd mobile/ios && pod install --repo-update
```

### Metro bundler port conflict

If port 8081 is in use, pass `--port`:

```bash
npx expo run:ios --port 8082
```

## What `expo run:ios` does under the hood

1. **Prebuild** (`expo prebuild`) — reads `app.json` and generates a bare
   React Native project in `mobile/ios/` and (if targeting Android) `mobile/android/`.
   Native packages declared in `package.json` are auto-linked via Expo's
   autolinking; no manual `Podfile` edits are needed.
2. **CocoaPods** (`pod install`) — resolves and installs iOS native dependencies.
3. **Xcode build** — compiles Swift/ObjC native code and produces an `.app` bundle.
4. **Simulator launch** — boots the target simulator and installs the `.app`.
5. **Metro** — starts the JS bundler; the app loads the bundle over a local
   WebSocket and hot-reloads on file changes.

## Version pins

| Package | Version | Notes |
|---------|---------|-------|
| `expo` | `~54.0.0` | RN 0.81, React 19.1, New Architecture |
| `@couchbase/couchbase-lite-react-native` | `^1.1.0` | Needs New Arch (`newArchEnabled: true`) |
| `expo-dev-client` | `~6.0.21` | Enables custom native modules in dev builds |
