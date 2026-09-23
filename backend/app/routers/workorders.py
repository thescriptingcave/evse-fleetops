"""Maintenance work orders + technician notes (synced to mobile)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..db import Store
from ..keys import now_iso, workorder_key
from ..live import broker
from ..models import WorkOrderCreate, WorkOrderNote, WorkOrderPatch

router = APIRouter(prefix="/api/workorders", tags=["workorders"])


def _with_id(doc: dict, key: str) -> dict:
    """Expose the doc key (minus the `wo::` prefix) as `id`, which clients address it by."""
    return {**doc, "id": key.removeprefix("wo::")}


@router.get("")
async def list_workorders(
    request: Request,
    status: str | None = None,
    station_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    store: Store = request.app.state.store
    where = ['type = "workorder"']
    params: dict = {}
    if status:
        where.append("status = $status")
        params["status"] = status
    if station_id:
        where.append("station_id = $station_id")
        params["station_id"] = station_id
    sql = (
        "SELECT META(w).id AS doc_key, w.* FROM `fleetops`.`_default`.`workorders` w "
        f"WHERE {' AND '.join(where)} ORDER BY w.updated_ts DESC LIMIT {int(limit)}"
    )
    rows = []
    async for r in store.query(sql, **params):
        key = r.pop("doc_key")
        rows.append(_with_id(r, key))
    return rows


@router.post("", status_code=201)
async def create_workorder(payload: WorkOrderCreate, request: Request) -> dict:
    store: Store = request.app.state.store
    now = now_iso()
    doc = {
        "type": "workorder",
        "station_id": payload.station_id,
        "title": payload.title,
        "description": payload.description,
        "priority": payload.priority,
        "status": "OPEN",
        "assignee": payload.assignee,
        "notes": [],
        "created_ts": now,
        "updated_ts": now,
    }
    key = workorder_key()
    await store.upsert("workorders", key, doc)
    await broker.publish(
        {"type": "workorder", "event": "created", "workorder_id": key.split("::", 1)[1], "station_id": payload.station_id}
    )
    return _with_id(doc, key)


@router.get("/{workorder_id}")
async def get_workorder(workorder_id: str, request: Request) -> dict:
    store: Store = request.app.state.store
    doc = await store.get("workorders", workorder_key(workorder_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="workorder not found")
    return _with_id(doc, workorder_key(workorder_id))


@router.put("/{workorder_id}")
async def update_workorder(workorder_id: str, payload: WorkOrderPatch, request: Request) -> dict:
    store: Store = request.app.state.store

    def apply(doc: dict) -> None:
        for field in ("status", "priority", "assignee", "title", "description"):
            value = getattr(payload, field)
            if value is not None:
                doc[field] = value
        doc["updated_ts"] = now_iso()

    doc = await store.mutate("workorders", workorder_key(workorder_id), apply)
    if doc is None:
        raise HTTPException(status_code=404, detail="workorder not found")
    await broker.publish(
        {"type": "workorder", "event": "updated", "workorder_id": workorder_id, "station_id": doc.get("station_id")}
    )
    return _with_id(doc, workorder_key(workorder_id))


@router.post("/{workorder_id}/notes", status_code=201)
async def add_workorder_note(workorder_id: str, note: WorkOrderNote, request: Request) -> dict:
    store: Store = request.app.state.store

    def apply(doc: dict) -> None:
        now = now_iso()
        doc.setdefault("notes", []).append({"author": note.author, "text": note.text, "ts": now})
        doc["updated_ts"] = now

    doc = await store.mutate("workorders", workorder_key(workorder_id), apply)
    if doc is None:
        raise HTTPException(status_code=404, detail="workorder not found")
    await broker.publish(
        {"type": "workorder", "event": "note", "workorder_id": workorder_id, "station_id": doc.get("station_id")}
    )
    return _with_id(doc, workorder_key(workorder_id))
