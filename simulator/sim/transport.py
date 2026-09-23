"""REST push transport with buffering + exponential backoff for intermittent links."""

from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("evse.sim.transport")

# Statuses worth retrying; any other 4xx means the payload itself is bad and
# replaying it would wedge the buffer forever.
_RETRYABLE_4XX = {404, 408, 425, 429}


class Transport:
    def __init__(self, base_url: str, max_buffer: int = 500) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=10.0)
        # Pending data, oldest first; flushed ahead of new data so the backend
        # sees readings and session events in chronological order.
        self.samples: list[dict] = []
        self.session_events: list[dict] = []
        self.max_buffer = max_buffer
        self._backoff = 1.0

    async def close(self) -> None:
        await self.client.aclose()

    @property
    def buffered(self) -> int:
        return len(self.samples) + len(self.session_events)

    async def send_batch(self, batch: dict) -> tuple[bool, int]:
        """Send a batch (plus anything buffered); on failure keep it and back off. Returns (sent, dropped)."""
        had_backlog = self.buffered > 0
        self.samples.extend(batch.get("samples", []))
        self.session_events.extend(batch.get("session_events", []))
        payload = {"samples": self.samples, "session_events": self.session_events}

        try:
            resp = await self.client.post(f"{self.base_url}/api/telemetry/batch", json=payload)
        except Exception as exc:
            log.warning("telemetry push failed (offline?): %s", exc)
        else:
            if resp.status_code == 200:
                if had_backlog:
                    log.info("flushed backlog; delivered %d samples", len(self.samples))
                self._clear()
                self._backoff = 1.0
                return True, 0
            if 400 <= resp.status_code < 500 and resp.status_code not in _RETRYABLE_4XX:
                log.error("batch rejected status=%s, discarding: %s", resp.status_code, resp.text[:300])
                dropped = len(self.samples)
                self._clear()
                return False, dropped
            log.warning("batch rejected status=%s: %s", resp.status_code, resp.text[:200])

        await asyncio.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, 30.0)
        return False, self._trim()

    def _clear(self) -> None:
        self.samples = []
        self.session_events = []

    def _trim(self) -> int:
        """Drop the oldest samples beyond max_buffer. Session events are few and are always kept."""
        dropped = max(0, len(self.samples) - self.max_buffer)
        if dropped:
            del self.samples[:dropped]
        return dropped

    async def discover_stations(self) -> list[dict]:
        """Adopt stations already registered with the backend."""
        try:
            resp = await self.client.get(f"{self.base_url}/api/stations", timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
            log.warning("station discovery got HTTP %s from %s", resp.status_code, self.base_url)
        except Exception as exc:
            log.warning("station discovery failed: %s", exc)
        return []
