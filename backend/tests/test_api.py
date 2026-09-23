"""Integration tests against a live local Couchbase (needs `make up` + bootstrap)."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from httpx import ASGITransport, AsyncClient

from app.bootstrap import ensure_infra
from app.main import app


@pytest.fixture(scope="session", autouse=True)
async def _infra():
    await ensure_infra()
    yield


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_stations_seeded(client):
    r = await client.get("/api/stations")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 12
    serials = {row["serial"] for row in rows}
    assert "EVSE-000" in serials


async def test_station_lookup_and_404(client):
    r = await client.get("/api/stations/EVSE-000")
    assert r.status_code == 200
    assert r.json()["name"] == "Downtown Garage A"

    r = await client.get("/api/stations/NOPE-999")
    assert r.status_code == 404


async def test_telemetry_batch_updates_station(client):
    payload = {
        "samples": [
            {
                "station_id": "EVSE-000",
                "ts": "2026-09-22T12:00:00.000Z",
                "status": "CHARGING",
                "meter_kwh": 12.5,
                "temperature_c": 31.2,
                "humidity_pct": 44.0,
                "vibration_mm_s": 1.3,
            }
        ]
    }
    r = await client.post("/api/telemetry/batch", json=payload)
    assert r.status_code == 200
    assert r.json()["accepted"] == 1

    station = (await client.get("/api/stations/EVSE-000")).json()
    assert station["status"] == "CHARGING"
    assert station["meter_kwh"] == 12.5


async def test_timeseries(client):
    sample = {
        "station_id": "EVSE-000",
        "ts": "2026-09-21T08:00:00.000Z",
        "status": "AVAILABLE",
        "meter_kwh": 10.0,
        "temperature_c": 31.2,
    }
    r = await client.post("/api/telemetry/batch", json={"samples": [sample]})
    assert r.status_code == 200

    r = await client.get(
        "/api/stations/EVSE-000/timeseries",
        params={"metric": "temperature_c", "from_ts": "2026-09-21T08:00:00Z", "to_ts": "2026-09-21T08:00:59Z"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["metric"] == "temperature_c"
    assert [p["value"] for p in body["points"]] == [pytest.approx(31.2)]


async def test_chademo_connector_accepted(client):
    sid = uuid4().hex
    events = [
        {"station_id": "EVSE-011", "event": "start", "ts": "2026-09-22T09:00:00.000Z",
         "connector": "CHAdeMO", "session_id": sid, "start_meter_kwh": 1.0},
        {"station_id": "EVSE-011", "event": "end", "ts": "2026-09-22T09:10:00.000Z",
         "session_id": sid, "kwh": 2.0},
    ]
    r = await client.post("/api/telemetry/batch", json={"session_events": events})
    assert r.status_code == 200
    assert r.json()["session_events"] == 2


async def test_session_lifecycle(client):
    sid = uuid4().hex
    start = {
        "session_events": [
            {
                "station_id": "EVSE-001",
                "event": "start",
                "ts": "2026-09-22T10:00:00.000Z",
                "connector": "CCS2",
                "session_id": sid,
                "start_meter_kwh": 100.0,
            }
        ]
    }
    r = await client.post("/api/telemetry/batch", json=start)
    assert r.json()["session_events"] == 1
    active = (await client.get("/api/sessions/active")).json()
    assert [s for s in active if s["station_id"] == "EVSE-001"]

    end = {
        "session_events": [
            {
                "station_id": "EVSE-001",
                "event": "end",
                "ts": "2026-09-22T10:40:00.000Z",
                "end_meter_kwh": 142.0,
            }
        ]
    }
    r = await client.post("/api/telemetry/batch", json=end)
    assert r.json()["session_events"] == 1

    sessions = (await client.get("/api/sessions", params={"station_id": "EVSE-001"})).json()
    mine = [s for s in sessions if s["id"] == sid]
    assert len(mine) == 1
    assert mine[0]["state"] == "COMPLETED"
    assert mine[0]["kwh_delivered"] == pytest.approx(42.0)


async def test_session_end_survives_restart(client):
    """Active sessions are reloaded from Couchbase, so an end after a restart still closes them."""
    from app.live import broker
    from app.routers.telemetry import load_active_sessions

    sid = uuid4().hex
    start = {"station_id": "EVSE-004", "event": "start", "ts": "2026-09-22T11:00:00.000Z",
             "session_id": sid, "start_meter_kwh": 5.0}
    await client.post("/api/telemetry/batch", json={"session_events": [start]})

    broker.active_sessions.clear()  # simulate a backend restart
    await load_active_sessions(client._transport.app.state.store)
    assert broker.active_sessions["EVSE-004"]["id"] == sid

    end = {"station_id": "EVSE-004", "event": "end", "ts": "2026-09-22T11:30:00.000Z", "kwh": 3.5}
    await client.post("/api/telemetry/batch", json={"session_events": [end]})
    sessions = (await client.get("/api/sessions", params={"station_id": "EVSE-004"})).json()
    assert [s["state"] for s in sessions if s["id"] == sid] == ["COMPLETED"]


async def test_operator_override_survives_telemetry(client):
    r = await client.patch("/api/stations/EVSE-005", json={"status": "MAINTENANCE", "reason": "test"})
    assert r.status_code == 200
    try:
        from app.keys import now_iso

        sample = {"station_id": "EVSE-005", "ts": now_iso(), "status": "CHARGING", "meter_kwh": 1.0}
        await client.post("/api/telemetry/batch", json={"samples": [sample]})
        assert (await client.get("/api/stations/EVSE-005")).json()["status"] == "MAINTENANCE"
    finally:
        await client.patch("/api/stations/EVSE-005", json={"status": "AVAILABLE"})
    assert (await client.get("/api/stations/EVSE-005")).json()["status"] == "AVAILABLE"


async def test_workorder_crud_and_notes(client):
    created = (
        await client.post(
            "/api/workorders",
            json={
                "station_id": "EVSE-003",
                "title": "Replace display board",
                "priority": "HIGH",
                "assignee": "tech_garcia",
            },
        )
    ).json()
    wid = created["id"]
    assert created["status"] == "OPEN"

    listed = (await client.get("/api/workorders")).json()
    assert all(w.get("id") for w in listed)
    assert wid in {w["id"] for w in listed}

    got = (await client.get(f"/api/workorders/{wid}")).json()
    assert got["station_id"] == "EVSE-003"

    note = (await client.post(f"/api/workorders/{wid}/notes", json={"author": "tech_garcia", "text": "Board on order"})).json()
    assert len(note["notes"]) == 1

    updated = (await client.put(f"/api/workorders/{wid}", json={"status": "IN_PROGRESS"})).json()
    assert updated["status"] == "IN_PROGRESS"


async def test_manuals(client):
    r = await client.get("/api/manuals")
    assert r.status_code == 200
    assert any(m["model"] == "VoltHub DC 350" for m in r.json())


async def test_fleet_overview(client):
    r = await client.get("/api/fleet/overview")
    assert r.status_code == 200
    body = r.json()
    assert sum(body["station_totals"].values()) >= 12
    assert body["kwh_today"] >= 0