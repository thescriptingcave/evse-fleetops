"""Server-Sent Events stream used by the dashboard for live updates."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request

from ..live import broker
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/stream")
async def stream(request: Request):
    async def event_gen():
        yield {"event": "snapshot", "data": json.dumps(broker.snapshot())}
        async for ev in broker.subscribe():
            yield {"event": ev.get("type", "event"), "data": json.dumps(ev)}

    return EventSourceResponse(
        event_gen(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        ping=15,
    )