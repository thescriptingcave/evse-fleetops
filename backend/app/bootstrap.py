"""Idempotent Couchbase schema provisioning + seed data.

Used both by scripts/bootstrap.py (standalone) and on backend startup
(settings.bootstrap_on_startup / seed_on_startup).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from couchbase.management.buckets import BucketSettings
from couchbase.management.collections import CreateCollectionSettings

from .config import COLLECTIONS, get_settings
from .keys import manual_key, now_iso, session_key, station_key, workorder_key

STATION_SITES = [
    dict(serial="EVSE-000", name="Downtown Garage A", site_type="garage", model="VoltHub DC 350", lat=40.7128, lon=-74.0060),
    dict(serial="EVSE-001", name="Downtown Garage B", site_type="garage", model="Pulse AC 22", lat=40.7150, lon=-74.0080),
    dict(serial="EVSE-002", name="Airport P2 Level 1", site_type="parking", model="QuadCore DC 150", lat=40.6413, lon=-73.7781),
    dict(serial="EVSE-003", name="Airport P2 Level 2", site_type="parking", model="QuadCore DC 150", lat=40.6413, lon=-73.7781),
    dict(serial="EVSE-004", name="Riverside Depot", site_type="remote", model="GridLink AC 7", lat=40.5833, lon=-74.0667),
    dict(serial="EVSE-005", name="Birchwood Plaza", site_type="parking", model="Pulse AC 22", lat=40.6780, lon=-73.9000),
    dict(serial="EVSE-006", name="Harbor Freight Yard", site_type="remote", model="GridLink AC 7", lat=40.6530, lon=-74.0930),
    dict(serial="EVSE-007", name="Metro Transit Depot", site_type="garage", model="VoltHub DC 350", lat=40.7700, lon=-73.9300),
    dict(serial="EVSE-008", name="Tech Campus Garage", site_type="garage", model="Pulse AC 22", lat=40.7520, lon=-74.0000),
    dict(serial="EVSE-009", name="Summit Ridge Stop", site_type="remote", model="QuadCore DC 150", lat=41.0830, lon=-74.1730),
    dict(serial="EVSE-010", name="Oakdale Transfer", site_type="remote", model="GridLink AC 7", lat=40.8490, lon=-74.0700),
    dict(serial="EVSE-011", name="Civic Center Deck", site_type="parking", model="VoltHub DC 350", lat=40.7330, lon=-74.0020),
]

MANUALS = [
    dict(key="volt-hub-350", model="VoltHub DC 350", title="VoltHub DC 350 Installation & Service Manual", version="3.2.1"),
    dict(key="quad-core-150", model="QuadCore DC 150", title="QuadCore DC 150 Maintenance Guide", version="1.9.0"),
    dict(key="pulse-ac-22", model="Pulse AC 22", title="Pulse AC 22 Field Service Reference", version="2.0.4"),
    dict(key="gridlink-ac-7", model="GridLink AC 7", title="GridLink AC 7 Connectivity & Troubleshooting", version="1.4.2"),
]


async def ensure_schema() -> None:
    from acouchbase.cluster import Cluster
    from couchbase.auth import PasswordAuthenticator
    from couchbase.exceptions import BucketAlreadyExistsException
    from couchbase.options import ClusterOptions, ClusterTimeoutOptions

    s = get_settings()
    auth = PasswordAuthenticator(s.cb_username, s.cb_password)
    opts = ClusterOptions(auth, timeout_options=ClusterTimeoutOptions(timeout=timedelta(seconds=20)))
    cluster = await Cluster.connect(s.connection_string, opts)

    try:
        try:
            await cluster.buckets().get_bucket(s.bucket)
        except Exception:
            try:
                await cluster.buckets().create_bucket(
                    BucketSettings(name=s.bucket, ram_quota_mb=512, conflict_resolution_type="lww")
                )
                print(f"[bootstrap] created bucket {s.bucket}")
            except BucketAlreadyExistsException:
                pass

        bucket = cluster.bucket(s.bucket)
        await bucket.on_connect()
        manager = bucket.collections()

        existing = set()
        for scope in await manager.get_all_scopes():
            if scope.name == s.scope:
                existing = {c.name for c in scope.collections}
                break
        for name in COLLECTIONS:
            if name in existing:
                continue
            settings = None
            if name == "telemetry":
                settings = CreateCollectionSettings(max_expiry=timedelta(days=s.telemetry_ttl_days))
            await manager.create_collection(s.scope, name, settings=settings)
            print(f"[bootstrap] created collection {name} (scope {s.scope})")

        indexes = [
            f"CREATE PRIMARY INDEX `def_primary_{i}` ON `{s.bucket}`.`{s.scope}`.`{name}` USING GSI"
            for i, name in enumerate(COLLECTIONS)
        ]
        indexes += [
            f"CREATE INDEX `idx_stations_status` ON `{s.bucket}`.`{s.scope}`.`stations`(status) USING GSI",
            f"CREATE INDEX `idx_telemetry_station_ts` ON `{s.bucket}`.`{s.scope}`.`telemetry`(station_id, ts_ms) USING GSI",
            f"CREATE INDEX `idx_telemetry_ts` ON `{s.bucket}`.`{s.scope}`.`telemetry`(ts_ms) USING GSI",
            f"CREATE INDEX `idx_sessions_station_start` ON `{s.bucket}`.`{s.scope}`.`sessions`(station_id, start_ts) USING GSI",
            f"CREATE INDEX `idx_sessions_state` ON `{s.bucket}`.`{s.scope}`.`sessions`(state, start_ts) USING GSI",
            f"CREATE INDEX `idx_workorders_status_prio` ON `{s.bucket}`.`{s.scope}`.`workorders`(status, priority) USING GSI",
        ]
        for stmt in indexes:
            try:
                async for _row in cluster.query(stmt):
                    pass
            except Exception as exc:
                msg = str(exc).lower()
                if "already exists" in msg or "all keyspace ranges already covered" in msg:
                    continue
                print(f"[bootstrap] index warning: {exc}")
        print("[bootstrap] schema ok")
    finally:
        await cluster.close()


async def seed() -> None:
    from .db import Store

    store = Store()
    await store.connect()
    try:
        now = now_iso()
        for site in STATION_SITES:
            doc = {
                "type": "station",
                **site,
                "status": "AVAILABLE",
                "firmware": "4.12.6",
                "meter_kwh": 0.0,
                "temperature_c": None,
                "humidity_pct": None,
                "vibration_mm_s": None,
                "last_seen": None,
                "created_ts": now,
            }
            if await store.insert("stations", station_key(site["serial"]), doc):
                print(f"[bootstrap] seeded station {site['serial']} ({site['name']})")

        for m in MANUALS:
            doc = {"type": "manual", **m}
            if await store.insert("manuals", manual_key(m["key"]), doc):
                print(f"[bootstrap] seeded manual {m['key']}")

        sample_wo = [
            dict(
                station_id="EVSE-007",
                title="Replacement of connector latch assembly",
                description="Intermittent charging stop reported on connector 2. Fault code E14.",
                priority="HIGH",
                status="IN_PROGRESS",
                assignee="tech_garcia",
                notes=[{"author": "tech_garcia", "text": "Connector latch worn; replacement kit ordered.", "ts": now}],
            ),
            dict(
                station_id="EVSE-002",
                title="Firmware update to 4.12.6",
                description="Planned firmware rollout window for Airport P2 units.",
                priority="LOW",
                status="OPEN",
                assignee="tech_kim",
                notes=[],
            ),
        ]
        for i, wo in enumerate(sample_wo):
            doc = {"type": "workorder", **wo, "created_ts": now, "updated_ts": now}
            if await store.insert("workorders", workorder_key(f"sample-{i}"), doc):
                print(f"[bootstrap] seeded workorder {i}")

        tech = {
            "type": "technician",
            "username": "tech_garcia",
            "name": "Luis Garcia",
            "role": "Senior Field Technician",
        }
        if await store.insert("technicians", "tech::tech_garcia", tech):
            print("[bootstrap] seeded technician tech_garcia")
    finally:
        await store.close()


async def ensure_infra() -> None:
    await ensure_schema()
    if get_settings().seed_on_startup:
        await seed()


def run_cli() -> None:
    asyncio.run(ensure_infra())


if __name__ == "__main__":
    run_cli()