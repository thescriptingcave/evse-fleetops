from __future__ import annotations

from fastapi import APIRouter, Request

from ..db import Store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(
    request: Request,
    station_id: str | None = None,
    active_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    store: Store = request.app.state.store
    where = ['type = "session"']
    params: dict = {}
    if station_id:
        where.append("station_id = $station_id")
        params["station_id"] = station_id
    if active_only:
        where.append("state = 'ACTIVE'")
    sql = (
        "SELECT s.* FROM `fleetops`.`_default`.`sessions` s "
        f"WHERE {' AND '.join(where)} ORDER BY s.start_ts DESC LIMIT {int(limit)}"
    )
    rows = [r async for r in store.query(sql, **params)]
    for row in rows:
        row.pop("key", None)
    return rows


@router.get("/active")
async def active_sessions(request: Request) -> list[dict]:
    rows = [
        {k: v for k, v in d.items() if k != "key"}
        for d in request.app.state.broker.active_sessions.values()
    ]
    for row in rows:
        row.pop("key", None)
    return rows