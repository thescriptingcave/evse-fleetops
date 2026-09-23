from __future__ import annotations

import json
import random

from sim.fleet import StationSim, now_iso


def test_meter_is_monotonic():
    s = StationSim(serial="EVSE-000", rng=random.Random(7))
    s.status = "CHARGING"
    s.session = {"start_ts": now_iso(), "connector": "CCS2", "start_meter": s.meter_kwh, "id": "x"}
    prev = s.meter_kwh
    for _ in range(20):
        sample, _ = s.tick(3600, now_iso())
        assert sample["meter_kwh"] >= prev
        prev = sample["meter_kwh"]


def test_sensor_walk_stays_in_bounds():
    s = StationSim(serial="EVSE-001", rng=random.Random(3))
    for _ in range(200):
        sample, _ = s.tick(300, now_iso())
        assert 5 <= sample["temperature_c"] <= 85
        assert 15 <= sample["humidity_pct"] <= 98
        assert 0 <= sample["vibration_mm_s"] <= 20


def test_session_lifecycle_emits_end_with_kwh():
    s = StationSim(serial="EVSE-002", rng=random.Random(11))
    s.status = "CHARGING"
    s.session = {"start_ts": now_iso(), "connector": "CCS2", "start_meter": s.meter_kwh, "id": "abc"}
    start_meter = s.meter_kwh
    found = None
    for _ in range(200):
        _, events = s.tick(60, now_iso())
        for ev in events:
            if ev["event"] == "end":
                found = ev
                break
        if found:
            break
    assert found is not None, "session should end within 200 ticks"
    assert found["session_id"] == "abc"
    assert found["kwh"] > 0
    assert found["end_meter_kwh"] > start_meter


def test_random_seed_reproducible():
    a = StationSim(serial="EVSE-003", rng=random.Random(5))
    b = StationSim(serial="EVSE-003", rng=random.Random(5))
    ts = now_iso()  # same timestamp for both, or they can differ by a millisecond
    for _ in range(50):
        sa, _ = a.tick(300, ts)
        sb, _ = b.tick(300, ts)
        assert sa == sb

def test_connectors_match_backend_schema():
    # Must stay in sync with backend/app/models.py `Connector`.
    allowed = {"CCS1", "CCS2", "CHAdeMO", "TYPE2"}
    s = StationSim(serial="EVSE-000", model="VoltHub DC 350", rng=random.Random(1))
    assert {s.connect() for _ in range(200)} <= allowed


def _transport(handler):
    import httpx

    from sim.transport import Transport

    t = Transport("http://api")
    t.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    t._backoff = 0.0
    return t


async def test_transport_buffers_and_flushes_in_order():
    import httpx

    posted = []
    online = False

    def handler(request):
        if not online:
            raise httpx.ConnectError("down")
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={})

    t = _transport(handler)
    old = {"samples": [{"ts": "1"}], "session_events": [{"event": "start"}]}
    assert await t.send_batch(old) == (False, 0)
    online = True
    new = {"samples": [{"ts": "2"}], "session_events": [{"event": "end"}]}
    assert await t.send_batch(new) == (True, 0)
    assert posted == [
        {"samples": [{"ts": "1"}, {"ts": "2"}], "session_events": [{"event": "start"}, {"event": "end"}]}
    ]
    assert t.buffered == 0
    await t.close()


async def test_transport_discards_invalid_batch():
    import httpx

    t = _transport(lambda request: httpx.Response(422, json={"detail": "bad"}))
    sent, dropped = await t.send_batch({"samples": [{"ts": "1"}], "session_events": []})
    assert (sent, dropped) == (False, 1)
    assert t.buffered == 0
    await t.close()
