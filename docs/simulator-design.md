# EVSE FleetOps Simulator — Technical Design

A detailed reference for the fleet simulator: what it does, how it is built,
and every design decision behind it. Last updated 2026-09-23.

---

## Table of Contents

1. [Purpose and Role](#1-purpose-and-role)
2. [Directory Layout](#2-directory-layout)
3. [Architecture Overview](#3-architecture-overview)
4. [Entry Point and Main Loop](#4-entry-point-and-main-loop)
5. [Station State Machine](#5-station-state-machine)
6. [Sensor Physics](#6-sensor-physics)
7. [Session Lifecycle](#7-session-lifecycle)
8. [Transport Layer](#8-transport-layer)
9. [Configuration Reference](#9-configuration-reference)
10. [Test Suite](#10-test-suite)
11. [Design Decisions and Trade-offs](#11-design-decisions-and-trade-offs)
12. [Known Limitations](#12-known-limitations)

---

## 1. Purpose and Role

The simulator is a standalone Python process that impersonates a fleet of EVSE
(Electric Vehicle Supply Equipment) charging stations. It produces realistic
telemetry — sensor readings, status transitions, charging sessions — and pushes
that data to the backend API over HTTP.

Its job in the system is threefold:

- **Development target.** The backend and dashboard can be exercised without
  real hardware.
- **Integration test driver.** The automated test suite uses the simulator to
  verify end-to-end flows: telemetry ingestion, session management, alert
  deduplication, and operator overrides.
- **Load generator.** With `--speed` turned up the simulator compresses
  simulated time, letting a long-running scenario (hours of fleet activity)
  play out in seconds.

The simulator has no database of its own. It is stateless beyond what is held
in memory for the current run. All state that needs to persist (station
documents, session records, telemetry history) lives in the backend's Couchbase
instance.

---

## 2. Directory Layout

```
simulator/
├── pyproject.toml          project metadata, dependencies, pytest config
├── uv.lock                 pinned dependency tree
└── sim/
    ├── __init__.py         package marker (empty)
    ├── __main__.py         CLI entry point; main async loop
    ├── fleet.py            StationSim dataclass; per-station state machine
    ├── physics.py          continuous sensor dynamics (random walk)
    └── transport.py        HTTP transport; buffering; exponential backoff
tests/
└── test_sim.py             7 async test cases covering core behaviour
```

**Runtime dependencies** (from `pyproject.toml`):

| Package | Version | Use |
|---------|---------|-----|
| `httpx` | ≥0.27 | Async HTTP client for POSTing batches |

**Dev dependencies:**

| Package | Version | Use |
|---------|---------|-----|
| `pytest` | ≥8.3 | Test runner |
| `pytest-asyncio` | ≥0.24 | Async test support (`asyncio_mode = auto`) |

Python requirement: **≥3.12, <3.14**.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     __main__.py                         │
│                                                         │
│   ┌──────────┐  tick(dt,ts)  ┌──────────────────────┐  │
│   │StationSim│──────────────▶│  sample + events     │  │
│   │(×12)     │               │  (dicts)             │  │
│   └──────────┘               └──────────┬───────────┘  │
│        │                                │               │
│        │  physics.py                    │               │
│        │  walk()/temperature()          ▼               │
│        │  humidity()/vibration()  ┌──────────┐         │
│        └────────────────────────▶│ Transport│         │
│                                   │ .send_   │         │
│                                   │ batch()  │         │
│                                   └────┬─────┘         │
└────────────────────────────────────────│────────────────┘
                                         │ POST /api/telemetry/batch
                                         ▼
                                  ┌─────────────┐
                                  │  Backend API │
                                  │  :8010       │
                                  └─────────────┘
```

Three concerns are cleanly separated:

- **`fleet.py`** — *what* each station is doing (state, physics, session events)
- **`physics.py`** — *how* continuous sensors evolve over time
- **`transport.py`** — *how* data reaches the backend reliably

`__main__.py` orchestrates them: one tick per `--interval` seconds, collecting
all station outputs into a single batch and handing it to `Transport`.

---

## 4. Entry Point and Main Loop

**File:** `sim/__main__.py`

### CLI Parsing — `parse_args()`

```python
def parse_args() -> argparse.Namespace
```

| Argument | Env var | Default | Description |
|----------|---------|---------|-------------|
| `--url` | `EVSE_API_URL` | `http://localhost:8010` | Backend base URL |
| `--interval` | — | `5.0` | Wall-clock seconds between ticks |
| `--speed` | — | `60.0` | Simulated seconds per tick (`dt`) |
| `--stations` | — | `12` | Maximum stations to run |
| `--seed` | — | `None` | Integer seed for reproducible runs |
| `--no-sessions` | — | `False` | Suppress session START/END events |
| `--duration` | — | `0` | Stop after N seconds (0 = run forever) |

`--speed` and `--interval` are independent. With the defaults (interval=5s,
speed=60s) each 5-second wall-clock tick represents 1 minute of simulated
time. Setting `--speed 1` makes the simulation run in real time.

### Startup Sequence

```
1. parse_args()
2. logging.basicConfig(level=INFO)
3. rng = Random(seed)
4. transport = Transport(url)
5. stations = transport.discover_stations()
      └─ falls back to DEFAULT_SITES if empty
6. For each station: StationSim(…, rng=Random(f"{seed or 0}-{serial}"))
7. deadline = time.monotonic() + duration  (or infinity if duration == 0)
8. Enter main loop
```

### Main Loop

```python
tick_n = 0
while time.monotonic() < deadline:
    tick_n += 1
    ts = now_iso()

    batch = {"samples": [], "session_events": []}
    for station in stations:
        sample, events = station.tick(dt=args.speed, ts=ts)
        batch["samples"].append(sample)
        if not args.no_sessions:
            batch["session_events"].extend(events)

    ok, dropped = await transport.send_batch(batch)

    if tick_n % 10 == 0:
        log.info("tick=%d charging=%d total_meter=%.1f buffer=%d dropped=%d",
                 tick_n, charging_count, total_meter,
                 transport.buffered, total_dropped)

    await asyncio.sleep(args.interval)

await transport.close()
```

Every 10 ticks the loop logs a stats line:
- Number of stations currently CHARGING
- Sum of all station meter readings (total fleet kWh)
- Current transport buffer depth (samples pending delivery)
- Cumulative dropped sample count

---

## 5. Station State Machine

**File:** `sim/fleet.py`

### `StationSim` Dataclass

```python
@dataclass
class StationSim:
    serial:        str
    name:          str
    site_type:     str          # "garage" | "parking" | "remote"
    model:         str          # charger hardware model string
    rng:           Random       # per-station seeded RNG

    # Live state (mutated every tick)
    status:        str   = "AVAILABLE"
    meter_kwh:     float = field(default_factory=…)   # 300–4000 kWh initial
    temperature_c: float = 24.0
    humidity_pct:  float = 55.0
    vibration_mm_s:float = 0.4
    load_kw:       float = 0.0
    rate_kw:       float = field(default_factory=…)   # derived from model
    session:       dict | None = None
    transition_in: float = 0    # countdown for timed state exits
```

`__post_init__` derives `rate_kw` from the model name and randomises the
initial meter reading:

```python
if "350" in model:
    rate_kw = rng.uniform(7, 30)   # DC fast charger
else:
    rate_kw = rng.uniform(3.5, 7.5)  # AC level 2

meter_kwh = rng.uniform(300, 4000)  # pre-aged meter
```

### State Diagram

```
                   ┌──────────────────────────────┐
                   │                              │
                   ▼  p=0.0015 / tick             │
              ┌─────────┐                    ┌────┴────┐
  ──start──▶  │AVAILABLE│ ──p=0.0040/tick──▶ │ FAULTED │
              └────┬────┘                    └────┬────┘
                   │                              │
               p=0.15/tick               3–12 tick countdown
               (emit START)                       │
                   │                              ▼
                   ▼                       ┌─────────────┐
              ┌─────────┐                  │ MAINTENANCE │
              │CHARGING │                  └──────┬──────┘
              └────┬────┘                         │
               p=0.09/tick               3–12 tick countdown
               (emit END)                         │
                   │                              │
                   └──────────────────────────────┘
                              │
                   ┌──────────┘  p=0.0015 / tick (from AVAILABLE)
                   ▼
              ┌─────────┐
              │ OFFLINE │
              └────┬────┘
               2–8 tick countdown
                   │
                   └──────▶ AVAILABLE
```

### `tick(dt, ts)` — The Core Method

```python
def tick(self, dt: float, ts: str) -> tuple[dict, list[dict]]:
```

`dt` is the number of **simulated** seconds this tick represents (controlled by
`--speed`). `ts` is the ISO 8601 timestamp to stamp all outputs with.

**Execution order inside `tick()`:**

1. **Decrement transition counter** (if in a timed state)
2. **Evaluate transitions** based on current status:

   | From | Condition | To | Side-effect |
   |------|-----------|----|-------------|
   | `AVAILABLE` | `roll < 0.0015` | `OFFLINE` | countdown = randint(2,8) |
   | `AVAILABLE` | `roll < 0.0040` | `FAULTED` | countdown = randint(3,12); reason = "fault E{10–42}" |
   | `AVAILABLE` | `roll < 0.15` | `CHARGING` | create session; emit START event |
   | `CHARGING` | `roll < 0.09` | `AVAILABLE` | emit END event; clear session |
   | `OFFLINE` | countdown == 0 | `AVAILABLE` | reason = "link restored" |
   | `FAULTED` | countdown == 0 | `MAINTENANCE` | countdown = randint(3,12) |
   | `MAINTENANCE` | countdown == 0 | `AVAILABLE` | — |

3. **Update sensor readings** (see [Section 6](#6-sensor-physics))
4. **Increment meter** (only while `CHARGING`):
   ```python
   load_kw = rate_kw * rng.uniform(0.8, 1.0)
   meter_kwh += load_kw * (dt / 3600)
   ```
5. **Build and return** the telemetry sample dict and any session events.

### Telemetry Sample Schema

```python
{
    "station_id":     "EVSE-000",
    "ts":             "2026-09-23T18:37:19.123Z",
    "status":         "CHARGING",
    "meter_kwh":      1234.567,
    "temperature_c":  48.2,
    "humidity_pct":   61.4,
    "vibration_mm_s": 2.3,
    "load_kw":        25.5
}
```

### Connector Selection — `connect()`

```python
def connect(self) -> str:
```

| Model contains `"350"` | Result |
|------------------------|--------|
| Yes (DC fast charger) | CCS1, CCS2, or CHAdeMO (equal probability) |
| No (AC level 2) | always CCS2 |

---

## 6. Sensor Physics

**File:** `sim/physics.py`

All continuous sensors (temperature, humidity, vibration) use the same
underlying **random walk** algorithm.

### `walk(value, target, rate, noise, rng, lo, hi) → float`

```python
def walk(value, target, rate, noise, rng, lo, hi) -> float:
    value += (target - value) * rate + rng.uniform(-noise, noise)
    return max(lo, min(hi, value))
```

| Parameter | Role |
|-----------|------|
| `value` | Current sensor reading |
| `target` | The value the sensor is converging toward |
| `rate` | Convergence speed (0–1). High = fast snap to target. |
| `noise` | ±magnitude of random oscillation per tick |
| `lo`, `hi` | Hard clamp bounds |

The algorithm produces a first-order lag response (like an RC circuit) with
additive white noise on top. It is called once per sensor per tick.

### Sensor Parameters

| Sensor | Target | Rate | Noise | Bounds |
|--------|--------|------|-------|--------|
| `temperature_c` | Status-dependent (see below) | 0.12 | ±0.35°C | 5–85°C |
| `humidity_pct` | 52 + gauss(0,4) | 0.05 | ±1.2% | 15–98% |
| `vibration_mm_s` | Status-dependent (see below) | 0.08–0.30 | ±0.1–0.5 | 0–20 mm/s |

**Temperature targets by status:**

| Status | Target °C | Rationale |
|--------|-----------|-----------|
| `FAULTED` | 60–75 (random per tick) | Thermal runaway / overheating |
| `CHARGING` | 26 + (load_pct × 22) | Load-driven heating |
| `AVAILABLE` / `OFFLINE` / `MAINTENANCE` | 24°C (remote sites: 24.5°C) | Ambient |

**Vibration targets by status:**

| Status | Target mm/s | Rationale |
|--------|-------------|-----------|
| `FAULTED` | 12–16 (random per tick) | Mechanical fault |
| `CHARGING` | 1.5 + load_kw × 0.12 | Compressor/cooling fan |
| Otherwise | 0.4 | Background vibration |

**Humidity** is status-independent. The target drifts around 52% with Gaussian
noise (`gauss(0, 4)`) each tick, simulating slow ambient changes.

---

## 7. Session Lifecycle

Sessions represent real EV charging events. The simulator produces `start` and
`end` events that the backend uses to populate the `sessions` collection.

### Session Start

Triggered when a station in `AVAILABLE` rolls `< 0.15` during `tick()`.

```python
session = {
    "id":           uuid4().hex,
    "start_ts":     ts,
    "connector":    self.connect(),
    "start_meter":  round(self.meter_kwh, 3)
}
```

Event emitted:
```python
{
    "station_id":       serial,
    "event":            "start",
    "ts":               ts,
    "connector":        "CCS2",
    "session_id":       "a3f8…",
    "start_meter_kwh":  1200.000
}
```

### Session Active

Each tick while `CHARGING`:

```python
load_kw = rate_kw * rng.uniform(0.8, 1.0)  # 80–100% of rated power
meter_kwh += load_kw * (dt / 3600)          # accumulate energy
```

The 20% load variation simulates real-world power negotiation between the
vehicle's BMS and the charger.

### Session End

Triggered when a station in `CHARGING` rolls `< 0.09` during `tick()`.

```python
kwh_delivered = round(meter_kwh - session["start_meter"], 3)
```

Event emitted:
```python
{
    "station_id":    serial,
    "event":         "end",
    "ts":            ts,
    "connector":     "CCS2",
    "session_id":    "a3f8…",
    "end_meter_kwh": 1234.567,
    "kwh":           34.567
}
```

The session dict is then cleared and `load_kw` resets to 0.

### Expected Session Duration

With a 9%/tick exit probability and `--interval 5 --speed 60` (each tick =
1 minute simulated), the geometric distribution gives a mean session length
of `1/0.09 ≈ 11 ticks = ~11 simulated minutes`. Energy delivered per session
is therefore approximately `rate_kw × 11/60` kWh.

### Sessions Disabled

Passing `--no-sessions` causes `__main__.py` to discard all session events
before batching. Telemetry samples continue normally. This is useful for
testing pure telemetry ingestion without session side-effects.

---

## 8. Transport Layer

**File:** `sim/transport.py`

The `Transport` class isolates all network concerns from the simulation logic.

### Class Attributes

```python
class Transport:
    base_url:    str
    client:      httpx.AsyncClient   # timeout=10s
    samples:     list[dict]          # buffered samples (oldest first)
    session_events: list[dict]       # buffered session events
    max_buffer:  int = 500
    _backoff:    float = 1.0         # current backoff delay (seconds)
```

### `send_batch(batch)` — Full Algorithm

```
INPUT: batch = {"samples": [...], "session_events": [...]}

1. Prepend new data onto existing buffers (old data first):
      samples        = self.samples + batch["samples"]
      session_events = self.session_events + batch["session_events"]

2. Build payload:
      payload = {"samples": samples, "session_events": session_events}

3. POST payload to {base_url}/api/telemetry/batch
   (httpx.AsyncClient, 10s timeout)

4a. HTTP 200 → SUCCESS
      Clear both buffers
      Reset _backoff to 1.0
      Return (True, 0)

4b. HTTP 4xx, code NOT in {404, 408, 425, 429} → FATAL ERROR
      Log error (payload rejected, will not retry)
      dropped = len(samples) + len(session_events)
      Clear buffers
      Return (False, dropped)

4c. HTTP 4xx retryable, 5xx, or exception → TRANSIENT ERROR
      Keep buffers as-is
      Sleep _backoff seconds
      _backoff = min(_backoff * 2, 30.0)
      Trim oldest samples if len(samples) > max_buffer
      Return (False, dropped_from_trim)
```

### Retryable vs. Fatal 4xx Codes

```python
_RETRYABLE_4XX = {404, 408, 425, 429}
```

| Code | Meaning | Action |
|------|---------|--------|
| 404 | Backend not yet up | Retry |
| 408 | Request timeout | Retry |
| 425 | Too Early | Retry |
| 429 | Rate limited | Retry |
| 400 | Schema error | Drop (bad payload) |
| 401 | Unauthorized | Drop |
| 422 | Validation error | Drop |
| 5xx | Server error | Retry |

### Backoff Schedule

| Failure # | Backoff delay |
|-----------|---------------|
| 1 | 1 s |
| 2 | 2 s |
| 3 | 4 s |
| 4 | 8 s |
| 5 | 16 s |
| 6+ | 30 s (capped) |

Backoff resets to 1 s immediately on any successful delivery. This means a
brief outage (1–2 ticks) recovers quickly; a prolonged outage backs off to
30-second intervals to avoid flooding the backend on recovery.

### Buffer Management

The sample buffer holds at most `max_buffer` (500) entries. When the buffer
would exceed this, the **oldest** samples are dropped first. Session events
are never trimmed — they are small in volume and higher in business value than
raw telemetry samples.

When a previously-failed batch finally succeeds, the transport logs:
```
flushed backlog; delivered N samples
```

### Chronological Ordering Guarantee

New data is always appended **after** existing buffered data before sending:

```python
to_send = self.samples + new_samples      # old before new
```

This ensures the backend always receives samples in ascending timestamp order
even after network recovery, which matters for the backend's "late sample"
guard (samples older than the station's newest are stored but not applied to
live state).

### `discover_stations()`

```python
async def discover_stations(self) -> list[dict]:
    response = await self.client.get("/api/stations", timeout=5.0)
    return response.json()  # or [] on error
```

Called once at startup. If the backend is reachable, the simulator adopts the
registered stations (using their serial numbers, names, site types, models)
instead of the hardcoded `DEFAULT_SITES`. This enables the simulator to match
whatever station catalogue the backend has been seeded with.

---

## 9. Configuration Reference

### Environment Variables

| Variable | Used by | Default | Description |
|----------|---------|---------|-------------|
| `EVSE_API_URL` | `__main__.py` | `http://localhost:8010` | Backend base URL |

### CLI Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--url` | str | `$EVSE_API_URL` | Backend base URL (overrides env var) |
| `--interval` | float | `5.0` | Wall-clock seconds per tick |
| `--speed` | float | `60.0` | Simulated seconds per tick (physics dt) |
| `--stations` | int | `12` | Max stations to simulate |
| `--seed` | int | `None` | RNG seed (omit for non-deterministic runs) |
| `--no-sessions` | flag | `False` | Suppress session START/END events |
| `--duration` | float | `0` | Stop after N seconds (0 = run forever) |

### Hardcoded Constants

**`fleet.py`**

| Constant | Value | Description |
|----------|-------|-------------|
| Meter init range | 300–4000 kWh | Simulates pre-aged stations |
| DC fast charger rate | 7–30 kW | For models containing "350" |
| AC level 2 rate | 3.5–7.5 kW | All other models |
| Load variation | 0.80–1.00 × rate | Power negotiation simulation |
| AVAILABLE → OFFLINE probability | 0.0015 / tick | ~1 event per 667 ticks |
| AVAILABLE → FAULTED probability | 0.0040 / tick | ~1 event per 250 ticks |
| AVAILABLE → CHARGING probability | 0.15 / tick | ~1 session start per 7 ticks |
| CHARGING → AVAILABLE probability | 0.09 / tick | Mean 11-tick session |
| OFFLINE countdown | 2–8 ticks | Recovery time |
| FAULTED countdown | 3–12 ticks | Fault response time |
| MAINTENANCE countdown | 3–12 ticks | Repair time |
| Fault codes | E10–E42 | Appears in `last_status_reason` on station doc |
| Stats log interval | 10 ticks | How often the main loop logs stats |

**`physics.py`**

| Sensor | Rate | Noise | Bounds | Notes |
|--------|------|-------|--------|-------|
| temperature_c | 0.12 | ±0.35°C | 5–85°C | Slow thermal lag |
| humidity_pct | 0.05 | ±1.2% | 15–98% | Very stable; drifting target |
| vibration_mm_s | 0.08–0.30 | ±0.1–0.5 | 0–20 mm/s | Varies by status |

**`transport.py`**

| Constant | Value | Description |
|----------|-------|-------------|
| HTTP timeout | 10 s | Per-request timeout |
| Max buffer | 500 samples | Before oldest are dropped |
| Backoff start | 1.0 s | Initial retry delay |
| Backoff max | 30.0 s | Cap on retry delay |
| Retryable 4xx codes | {404, 408, 425, 429} | Treated as transient |

### How to Run

```bash
# Default run (12 stations, 5s interval, 1-minute simulated time per tick)
cd simulator
uv run python -m sim

# Reproduce a specific run exactly
uv run python -m sim --seed 42

# Fast run for CI (30 seconds wall-clock, 60s/tick)
uv run python -m sim --duration 30 --speed 60

# Slow real-time run (good for watching the dashboard)
uv run python -m sim --interval 1 --speed 1

# Only 3 stations, no session events
uv run python -m sim --stations 3 --no-sessions

# Point at a non-default backend
EVSE_API_URL=http://192.168.1.50:8010 uv run python -m sim
```

---

## 10. Test Suite

**File:** `tests/test_sim.py`
**Runner:** pytest with `asyncio_mode = auto`

### Test Cases

**`test_meter_is_monotonic`**

Verifies that the cumulative energy meter never decreases. Forces the station
into `CHARGING` and runs 20 ticks, asserting `meter_kwh[n] >= meter_kwh[n-1]`
at every step. Guards against sign errors in the energy accumulation formula.

---

**`test_sensor_walk_stays_in_bounds`**

Runs 200 ticks with the station cycling through all statuses and checks that:
- `temperature_c` stays in [5, 85]
- `humidity_pct` stays in [15, 98]
- `vibration_mm_s` stays in [0, 20]

Guards against `walk()` producing values outside the declared clamp bounds.

---

**`test_session_lifecycle_emits_end_with_kwh`**

Forces a session to start and then runs up to 200 ticks until an `end` event
appears. Asserts that:
- The `end` event contains `kwh > 0`
- `end_meter_kwh >= start_meter_kwh`
- The session dict is cleared after the end event

Guards against sessions that start but never end, or that report negative
energy delivery.

---

**`test_random_seed_reproducible`**

Creates two `StationSim` instances with the same seed string. Runs both for
50 ticks and compares `meter_kwh`, `status`, and `load_kw` at every tick.
Asserts identical outputs. Guards against non-determinism that would break
reproducible test scenarios.

---

**`test_connectors_match_backend_schema`**

Starts 200 sessions across a single station and collects all connector types
from START events. Asserts every value is in `{"CCS1", "CCS2", "CHAdeMO",
"TYPE2"}`. (Note: `TYPE2` is in the allowed set for forward-compatibility but
the current simulator never generates it — it only produces `CCS1`, `CCS2`,
`CHAdeMO`.)

---

**`test_transport_buffers_and_flushes_in_order`**

Uses `httpx.MockTransport` to simulate a network outage:

1. First two batches return HTTP 503 → samples buffer up
2. Third batch returns HTTP 200 → all buffered samples flushed in one POST

Asserts that:
- The successful POST payload contains samples from all three batches
- Samples appear in chronological order (old before new)
- `transport.buffered` returns 0 after flush

Guards against reordering during backlog recovery and against buffer loss.

---

**`test_transport_discards_invalid_batch`**

Configures the mock to return HTTP 422. Sends a batch and asserts:
- `send_batch()` returns `(False, N)` where N = sample count sent
- `transport.buffered` returns 0 (buffer was cleared, not retained)

Guards against infinite retry loops on permanently-invalid payloads.

### Running the Tests

```bash
cd simulator
uv run pytest -v
```

Expected output:
```
tests/test_sim.py::test_meter_is_monotonic              PASSED
tests/test_sim.py::test_sensor_walk_stays_in_bounds     PASSED
tests/test_sim.py::test_session_lifecycle_emits_end_with_kwh  PASSED
tests/test_sim.py::test_random_seed_reproducible        PASSED
tests/test_sim.py::test_connectors_match_backend_schema PASSED
tests/test_sim.py::test_transport_buffers_and_flushes_in_order PASSED
tests/test_sim.py::test_transport_discards_invalid_batch PASSED
7 passed in 0.06s
```

---

## 11. Design Decisions and Trade-offs

### Seeded RNG per Station

Each `StationSim` gets its own `random.Random` instance seeded with
`f"{global_seed}-{serial}"`. This means:

- A single `--seed` makes the entire fleet deterministic.
- Each station's RNG is independent — changing one station's serial does not
  affect any other station's sequence.
- The seed string `f"0-EVSE-000"` is stable across runs even when the global
  seed is omitted (defaults to `0`).

The trade-off is that the combined seed is a string hash rather than a
structured integer, which is slightly less principled but practically reliable.

### Physics via Random Walk

All continuous sensors use the same `walk()` function from `physics.py`. This
was chosen over more complex models (Ornstein-Uhlenbeck, PID) because:

- It is simple to understand, tune, and test.
- The four parameters (`rate`, `noise`, `lo`, `hi`) are sufficient to model
  the range of EVSE sensor dynamics.
- The clamping bounds give hard guarantees that sensors never go out of range,
  which is important for avoiding schema-invalid telemetry.

The trade-off is that sensors do not exhibit correlation (e.g., temperature and
vibration are independent) and do not model phenomena like thermal runaway
gradually developing over time.

### Buffering in Transport, Not in Station

The `Transport` class owns the retry buffer. `StationSim` produces data and
hands it off; it has no knowledge of whether data was delivered. This keeps the
station logic pure (only physics and state) and the network resilience logic
concentrated in one place.

### Batch-per-Tick, Not Per-Station

All 12 stations' samples are collected into a single batch before sending. This
means one HTTP request per tick (regardless of station count) rather than 12.
The trade-off is that a single failed request delays all stations' data equally,
but this is better than 12 concurrent requests each with independent retry
timers.

### No Graceful Shutdown of Sessions

If the simulator is killed while a station is `CHARGING`, the corresponding
session START event has been delivered but no END event will follow. The backend
marks such sessions as `ABANDONED` when it restarts or when the next simulator
run starts and the session ID is never completed. This is acceptable for a
development tool; production systems would need a shutdown hook.

### Station Discovery at Startup Only

The simulator calls `discover_stations()` once at startup and never again. If
new stations are added to the backend while the simulator is running, they will
not be picked up until the next simulator restart. This simplicity is fine for
development; a production simulator would need periodic re-sync.

---

## 12. Known Limitations

| # | Limitation | Impact | Workaround |
|---|------------|--------|------------|
| 1 | Sessions are abandoned on mid-run FAULTED transition | Orphaned sessions in backend | Backend marks them ABANDONED on next start |
| 2 | No backoff jitter | Two simulators running together can thrash in sync | Not relevant with a single simulator instance |
| 3 | `TYPE2` connector never generated | Test allows it but simulator never emits it | Not a bug — TYPE2 is reserved for future models |
| 4 | Max buffer hard-coded at 500 | Cannot be configured via CLI | Edit `transport.py` or add `--max-buffer` arg |
| 5 | Station discovery has no retry | If backend is slow at startup, simulator falls back to DEFAULT_SITES immediately | Start the backend before the simulator |
| 6 | No SIGTERM handler | `make demo` kill may not drain the buffer | Use `--duration` instead of killing the process |
| 7 | Sensor correlations not modelled | Temperature and load are loosely coupled via target, but vibration/humidity are independent | Acceptable for telemetry testing purposes |
