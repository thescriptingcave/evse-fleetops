from __future__ import annotations

from fastapi import APIRouter, Request

from ..db import Store

router = APIRouter(prefix="/api/manuals", tags=["manuals"])


@router.get("")
async def list_manuals(request: Request, model: str | None = None) -> list[dict]:
    store: Store = request.app.state.store
    sql = "SELECT m.* FROM `fleetops`.`_default`.`manuals` m WHERE m.type = 'manual'"
    params: dict = {}
    if model:
        sql += " AND m.model = $model"
        params["model"] = model
    sql += " ORDER BY m.model"
    return [r async for r in store.query(sql, **params)]