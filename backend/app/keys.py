from datetime import datetime, timezone
from uuid import uuid4

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_ms(iso_ts: str) -> int:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return int((dt.timestamp() * 1000))


def station_key(serial: str) -> str:
    return f"station::{serial}"


def telemetry_key(serial: str, ts_ms: int) -> str:
    return f"telemetry::{serial}::{ts_ms}"


def session_key(uid: str | None = None) -> str:
    return f"session::{uid or uuid4().hex}"


def workorder_key(uid: str | None = None) -> str:
    return f"wo::{uid or uuid4().hex}"


def manual_key(uid: str) -> str:
    return f"manual::{uid}"


def new_id(prefix: str) -> str:
    return f"{prefix}::{uuid4().hex}"