"""EVSE FleetOps API application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Store
from .live import broker
from .routers import events, fleet, manuals, sessions, stations, telemetry, workorders
from .routers.telemetry import load_active_sessions

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("evse.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .bootstrap import ensure_infra

    settings = get_settings()

    store = Store()
    last_exc: Exception | None = None
    for attempt in range(1, 11):
        try:
            if settings.bootstrap_on_startup:
                # Best-effort schema/seed provisioning; tolerates already-existing objects.
                await ensure_infra()
            await store.connect()
            break
        except Exception as exc:  # Couchbase still warming up after `docker compose up`
            last_exc = exc
            log.warning("Couchbase not ready (attempt %d/10): %s", attempt, exc)
            await asyncio.sleep(3)
    else:
        raise RuntimeError(f"could not connect to Couchbase at {settings.connection_string}: {last_exc}")

    app.state.store = store
    app.state.broker = broker
    await load_active_sessions(store)
    log.info("connected to Couchbase bucket %s", settings.bucket)
    yield
    try:
        await store.close()
    except Exception:
        pass


app = FastAPI(title="EVSE FleetOps API", version=get_settings().version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (telemetry, stations, sessions, workorders, manuals, fleet, events):
    app.include_router(r.router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "couchbase": bool(getattr(app.state, "store", None))}