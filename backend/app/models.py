from typing import Literal

from pydantic import BaseModel, Field, field_validator

StationStatus = Literal["AVAILABLE", "CHARGING", "FAULTED", "MAINTENANCE", "OFFLINE"]
Connector = Literal["CCS1", "CCS2", "CHAdeMO", "TYPE2"]
Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
WorkOrderStatus = Literal["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]
Metric = Literal["temperature_c", "humidity_pct", "vibration_mm_s", "meter_kwh"]


class TimestampMixin(BaseModel):
    def _iso(cls, v):
        return v


class TelemetrySample(BaseModel):
    station_id: str
    ts: str
    status: StationStatus
    meter_kwh: float = Field(ge=0)
    temperature_c: float | None = None
    humidity_pct: float | None = None
    vibration_mm_s: float | None = None
    load_kw: float | None = None


class SessionEvent(BaseModel):
    station_id: str
    event: Literal["start", "end"]
    ts: str
    connector: Connector = "CCS2"
    session_id: str | None = None
    start_meter_kwh: float | None = None
    end_meter_kwh: float | None = None
    kwh: float | None = None


class TelemetryBatch(BaseModel):
    samples: list[TelemetrySample] = []
    session_events: list[SessionEvent] = []


class FleetOverview(BaseModel):
    station_totals: dict[str, int]
    active_sessions: int
    alerts: list[dict]
    kwh_today: float
    last_updated: str | None = None


class StationPatch(BaseModel):
    status: StationStatus
    reason: str | None = None


class ManualSummary(BaseModel):
    key: str
    model: str
    title: str
    version: str


class WorkOrderCreate(BaseModel):
    station_id: str
    title: str = Field(min_length=1, max_length=120)
    description: str | None = None
    priority: Priority = "MEDIUM"
    assignee: str | None = None


class WorkOrderPatch(BaseModel):
    status: WorkOrderStatus | None = None
    priority: Priority | None = None
    assignee: str | None = None
    title: str | None = None
    description: str | None = None


class WorkOrderNote(BaseModel):
    author: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()