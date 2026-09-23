"""Station master data + timeseries queries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..db import Store
from ..keys import station_key
from ..live import broker
from ..models import StationPatch

router = APIRouter(prefix="/api/stations", tags=["stations"])

_METRICS = {"temperature_c", "humidity_pct", "vibration_mm_s", "meter_kwh"}


@router.get("")
async def list_stations(
    request: Request,
    status: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[dict]:
    store: Store = request.app.state.store
    where = ['type = "station"']
    params: dict = {}
    if status:
        where.append("status = $status")
        params["status"] = status
    if q:
        where.append("(LOWER(name) LIKE $q OR LOWER(serial) LIKE $q)")
        params["q"] = f"%{q.lower()}%"
    sql = (
        "SELECT s.* FROM `fleetops`.`_default`.`stations` s "
        f"WHERE {' AND '.join(where)} ORDER BY s.serial LIMIT {int(limit)}"
    )
    rows = [r async for r in store.query(sql, **params)]
    for row in rows:
        row["latest"] = broker.latest.get(row["serial"])
    return rows


@router.get("/{serial}")
async def get_station(serial: str, request: Request) -> dict:
    store: Store = request.app.state.store
    doc = await store.get("stations", station_key(serial))
    if doc is None:
        raise HTTPException(status_code=404, detail="station not found")
    doc["latest"] = broker.latest.get(serial)
    return doc


@router.get("/{serial}/timeseries")
async def station_timeseries(
    serial: str,
    request: Request,
    metric: str = "temperature_c",
    from_ts: str | None = None,
    to_ts: str | None = None,
    bucket_minutes: int = 1,
) -> dict:
    if metric not in _METRICS:
        raise HTTPException(status_code=400, detail=f"metric must be one of {sorted(_METRICS)}")
    store: Store = request.app.state.store
    if await store.get("stations", station_key(serial)) is None:
        raise HTTPException(status_code=404, detail="station not found")

    bucket_ms = max(1, bucket_minutes) * 60_000
    where = ["t.station_id = $serial"]
    params: dict = {"serial": serial}
    if from_ts:
        from ..keys import epoch_ms
        where.append("t.ts_ms >= $from")
        params["from"] = epoch_ms(from_ts)
    if to_ts:
        from ..keys import epoch_ms
        where.append("t.ts_ms <= $to")
        params["to"] = epoch_ms(to_ts)

    sql = (
        f"SELECT (FLOOR(t.ts_ms / {bucket_ms}) * {bucket_ms}) AS ts_ms, "
        f"AVG(t.{metric}) AS val "
        "FROM `fleetops`.`_default`.`telemetry` t "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY FLOOR(t.ts_ms / {bucket_ms}) ORDER BY ts_ms"
    )
    points = []
    async for row in store.query(sql, **params):
        if row.get("val") is None:
            continue
        ts_ms = int(row["ts_ms"])
        points.append({"ts_ms": ts_ms, "value": round(row["val"], 3)})
    return {"serial": serial, "metric": metric, "bucket_minutes": bucket_minutes, "points": points}


@router.patch("/{serial}")
async def patch_station(serial: str, patch: StationPatch, request: Request) -> dict:
    from ..keys import now_iso
    from .telemetry import invalidate_station

    store: Store = request.app.state.store

    def apply(doc: dict) -> None:
        # AVAILABLE hands control back to the charger; anything else pins the status
        # so incoming telemetry doesn't immediately overwrite the operator's choice.
        doc["operator_status"] = None if patch.status == "AVAILABLE" else patch.status
        doc["status"] = patch.status
        if patch.reason:
            doc["last_status_reason"] = patch.reason

    doc = await store.mutate("stations", station_key(serial), apply)
    if doc is None:
        raise HTTPException(status_code=404, detail="station not found")
    invalidate_station(serial)
    if serial in broker.latest:
        broker.latest[serial]["status"] = patch.status
    await broker.publish(
        {"type": "status", "station_id": serial, "status": patch.status, "ts": now_iso(), "reason": patch.reason}
    )
    return doc