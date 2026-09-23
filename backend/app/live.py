"""In-process live event bus + latest-state cache used by the SSE stream."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from .keys import now_iso

TEMP_ALERT_C = 55.0
HUMIDITY_ALERT_PCT = 90.0
VIBRATION_ALERT_MM_S = 12.0


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        # station_id -> most recent telemetry reading for that station
        self.latest: dict[str, dict] = {}
        # ring buffer of the most recent 200 events (for initial snapshot)
        self.recent: list[dict] = []
        self._recent_max = 200
        # station_id -> active charging session doc
        self.active_sessions: dict[str, dict] = {}
        # station_id -> alert reasons currently raised (alerts are edge-triggered)
        self.raised_alerts: dict[str, set[str]] = {}
        # station_id -> monotonic time the station doc was last written from telemetry
        self.station_written: dict[str, float] = {}

    def new_alerts(self, station_id: str, reasons: dict[str, str]) -> list[str]:
        """Record the station's current alerts ({kind: message}); return messages for newly raised kinds."""
        prev = self.raised_alerts.get(station_id, set())
        self.raised_alerts[station_id] = set(reasons)
        return [msg for kind, msg in reasons.items() if kind not in prev]

    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "latest": {k: v for k, v in self.latest.items()},
            "recent": list(self.recent[-50:]),
        }

    def current_alerts(self) -> list[dict]:
        alerts = []
        for sid, r in self.latest.items():
            reasons = []
            if r.get("temperature_c") is not None and r["temperature_c"] >= TEMP_ALERT_C:
                reasons.append(f"temperature {r['temperature_c']:.1f}C")
            if r.get("vibration_mm_s") is not None and r["vibration_mm_s"] >= VIBRATION_ALERT_MM_S:
                reasons.append(f"vibration {r['vibration_mm_s']:.1f}mm/s")
            if r.get("humidity_pct") is not None and r["humidity_pct"] >= HUMIDITY_ALERT_PCT:
                reasons.append(f"humidity {r['humidity_pct']:.0f}%")
            if r.get("status") in ("FAULTED", "OFFLINE"):
                reasons.append(f"station {r.get('status','').lower()}")
            if reasons:
                alerts.append({"station_id": sid, "reasons": ", ".join(reasons), "ts": r.get("ts")})
        return alerts

    async def publish(self, event: dict) -> None:
        event = {"evt_ts": now_iso(), **event}
        self.recent.append(event)
        if len(self.recent) > self._recent_max:
            del self.recent[: len(self.recent) - self._recent_max]
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer: drop rather than block
                pass

    async def subscribe(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)


broker = EventBroker()