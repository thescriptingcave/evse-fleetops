"""Fleet-level aggregates for the dashboard overview."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from ..db import Store
from ..live import broker

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


@router.get("/overview")
async def overview(request: Request) -> dict:
    store: Store = request.app.state.store

    totals: dict[str, int] = {}
    sql = (
        "SELECT s.status AS status, COUNT(*) AS n "
        "FROM `fleetops`.`_default`.`stations` s WHERE s.type = 'station' "
        "GROUP BY s.status"
    )
    async for row in store.query(sql):
        totals[row.get("status") or "UNKNOWN"] = int(row.get("n", 0))

    kwh_today = 0.0
    today = datetime.now(timezone.utc).date()
    lower = today.isoformat()
    upper = (today + timedelta(days=1)).isoformat()
    sql = (
        "SELECT COALESCE(SUM(s.kwh_delivered), 0) AS total "
        "FROM `fleetops`._default.sessions s "
        "WHERE s.type = 'session' AND s.state = 'COMPLETED' "
        "AND s.end_ts >= $lower AND s.end_ts < $upper"
    )
    async for row in store.query(sql, lower=lower, upper=upper):
        kwh_today = float(row.get("total", 0))

    return {
        "station_totals": totals,
        "active_sessions": len(broker.active_sessions),
        "alerts": broker.current_alerts(),
        "kwh_today": round(kwh_today, 2),
        "last_updated": broker.recent[-1]["evt_ts"] if broker.recent else None,
    }