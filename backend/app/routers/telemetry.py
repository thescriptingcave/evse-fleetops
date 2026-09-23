"""Telemetry ingestion endpoint + live event fan-out."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Request

from ..config import get_settings
from ..db import Store
from ..keys import epoch_ms, session_key, station_key, telemetry_key
from ..live import (
    HUMIDITY_ALERT_PCT,
    TEMP_ALERT_C,
    VIBRATION_ALERT_MM_S,
    broker,
)
from ..models import TelemetryBatch

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# Station docs replicate to every technician device, so only rewrite them on a
# status change or at most this often; live readings go out over SSE instead.
STATION_WRITE_INTERVAL_S = 60.0


def _sample_alerts(sample) -> dict[str, str]:
    reasons: dict[str, str] = {}
    if sample.get("temperature_c") is not None and sample["temperature_c"] >= TEMP_ALERT_C:
        reasons["temperature"] = f"temperature {sample['temperature_c']:.1f}C"
    if sample.get("vibration_mm_s") is not None and sample["vibration_mm_s"] >= VIBRATION_ALERT_MM_S:
        reasons["vibration"] = f"vibration {sample['vibration_mm_s']:.1f}mm/s"
    if sample.get("humidity_pct") is not None and sample["humidity_pct"] >= HUMIDITY_ALERT_PCT:
        reasons["humidity"] = f"humidity {sample['humidity_pct']:.0f}%"
    return reasons


def invalidate_station(serial: str) -> None:
    """Force the next sample for this station to rewrite its doc (e.g. after an operator override)."""
    broker.station_written.pop(serial, None)


async def load_active_sessions(store: Store) -> None:
    """Rebuild the in-memory active-session map from Couchbase (survives backend restarts)."""
    sql = (
        "SELECT META(s).id AS doc_key, s.* FROM `fleetops`.`_default`.`sessions` s "
        "WHERE s.type = 'session' AND s.state = 'ACTIVE' ORDER BY s.start_ts"
    )
    broker.active_sessions.clear()
    async for row in store.query(sql):
        row["key"] = row.pop("doc_key")
        broker.active_sessions[row["station_id"]] = row  # latest start wins
    if broker.active_sessions:
        log.info("restored %d active sessions", len(broker.active_sessions))


@router.post("/batch")
async def ingest_batch(batch: TelemetryBatch, request: Request) -> dict:
    store: Store = request.app.state.store
    settings = get_settings()
    accepted = 0
    session_events = 0

    for s in batch.samples:
        sid, ts = s.station_id, s.ts
        ts_ms = epoch_ms(ts)
        doc = {
            "type": "telemetry",
            "station_id": sid,
            "ts": ts,
            "ts_ms": ts_ms,
            "status": s.status,
            "meter_kwh": s.meter_kwh,
            "temperature_c": s.temperature_c,
            "humidity_pct": s.humidity_pct,
            "vibration_mm_s": s.vibration_mm_s,
            "load_kw": s.load_kw,
        }
        await store.upsert(
            "telemetry", telemetry_key(sid, ts_ms), doc, ttl=timedelta(days=settings.telemetry_ttl_days)
        )
        accepted += 1

        last = broker.latest.get(sid)
        if last is not None and ts_ms < last["ts_ms"]:
            continue  # late/replayed sample: stored for history, but don't regress live state

        prev_status = last["status"] if last else None
        status = prev_status or s.status
        written = broker.station_written.get(sid)
        due = (
            last is None
            or last.get("sample_status") != s.status
            or written is None
            or time.monotonic() - written >= STATION_WRITE_INTERVAL_S
        )
        if due:
            def apply(station: dict) -> None:
                # An operator override (e.g. MAINTENANCE) wins over what the charger reports.
                station.update(
                    status=station.get("operator_status") or s.status,
                    meter_kwh=s.meter_kwh,
                    temperature_c=s.temperature_c,
                    humidity_pct=s.humidity_pct,
                    vibration_mm_s=s.vibration_mm_s,
                    last_seen=ts,
                )

            station = await store.mutate("stations", station_key(sid), apply)
            if station is None:
                log.warning("telemetry for unknown station %s; stored but not tracked", sid)
                continue
            broker.station_written[sid] = time.monotonic()
            status = station["status"]
            if prev_status is None:
                prev_status = status

        broker.latest[sid] = {**doc, "status": status, "sample_status": s.status}
        await broker.publish(
            {
                "type": "telemetry",
                "station_id": sid,
                "status": status,
                "ts": ts,
                "meter_kwh": s.meter_kwh,
                "temperature_c": s.temperature_c,
                "humidity_pct": s.humidity_pct,
                "vibration_mm_s": s.vibration_mm_s,
                "load_kw": s.load_kw,
            }
        )
        if status != prev_status:
            await broker.publish({"type": "status", "station_id": sid, "status": status, "ts": ts})

        for reason in broker.new_alerts(sid, _sample_alerts(doc)):
            await broker.publish(
                {"type": "alert", "station_id": sid, "reason": reason, "ts": ts, "status": status}
            )

    for ev in batch.session_events:
        session_events += 1
        await _handle_session_event(ev, store)

    return {"accepted": accepted, "session_events": session_events}


async def _handle_session_event(ev, store: Store) -> None:
    if ev.event == "start":
        previous = broker.active_sessions.pop(ev.station_id, None)
        if previous is not None:
            # A new session can't start while one is open: the end event was lost.
            previous = dict(previous)
            prev_key = previous.pop("key")
            previous.update(state="ABANDONED", end_ts=ev.ts)
            await store.upsert("sessions", prev_key, previous)
            log.warning("session %s on %s abandoned (no end event)", previous.get("id"), ev.station_id)

        uid = (ev.session_id or uuid4().hex).replace("session::", "")
        key = session_key(uid)
        doc = {
            "type": "session",
            "id": uid,
            "station_id": ev.station_id,
            "connector": ev.connector,
            "start_ts": ev.ts,
            "state": "ACTIVE",
            "start_meter_kwh": ev.start_meter_kwh,
            "kwh_delivered": 0.0,
            "end_ts": None,
        }
        await store.upsert("sessions", key, doc)
        broker.active_sessions[ev.station_id] = {**doc, "key": key}
        await broker.publish(
            {"type": "session", "event": "start", "station_id": ev.station_id, "session_id": uid, "ts": ev.ts}
        )
        return

    if ev.event == "end":
        active = broker.active_sessions.pop(ev.station_id, None)
        if active is not None:
            doc = dict(active)
            key = doc.pop("key")
        elif ev.session_id:
            key = session_key(ev.session_id.replace("session::", ""))
            doc = await store.get("sessions", key)
            if doc is None or doc.get("state") != "ACTIVE":
                log.warning("session end for %s: session %s not active; ignored", ev.station_id, ev.session_id)
                return
        else:
            log.warning("session end for %s without active session; ignored", ev.station_id)
            return
        if ev.kwh is not None:
            kwh = ev.kwh
        elif ev.end_meter_kwh is not None and doc.get("start_meter_kwh") is not None:
            kwh = max(0.0, ev.end_meter_kwh - doc["start_meter_kwh"])
        else:
            kwh = doc.get("kwh_delivered", 0.0)
        doc.update(state="COMPLETED", end_ts=ev.ts, kwh_delivered=kwh)
        await store.upsert("sessions", key, doc)
        await broker.publish(
            {
                "type": "session",
                "event": "end",
                "station_id": ev.station_id,
                "session_id": doc["id"],
                "kwh": kwh,
                "ts": ev.ts,
            }
        )


@router.get("/latest")
async def latest(request: Request) -> dict:
    """Snapshot of the most recent reading per station (polling fallback for SSE)."""
    return {"latest": broker.latest}
