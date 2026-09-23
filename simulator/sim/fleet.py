from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from random import Random
from uuid import uuid4

from . import physics

DEFAULT_SITES = [
    dict(serial="EVSE-000", name="Downtown Garage A", site_type="garage", model="VoltHub DC 350"),
    dict(serial="EVSE-001", name="Downtown Garage B", site_type="garage", model="Pulse AC 22"),
    dict(serial="EVSE-002", name="Airport P2 Level 1", site_type="parking", model="QuadCore DC 150"),
    dict(serial="EVSE-003", name="Airport P2 Level 2", site_type="parking", model="QuadCore DC 150"),
    dict(serial="EVSE-004", name="Riverside Depot", site_type="remote", model="GridLink AC 7"),
    dict(serial="EVSE-005", name="Birchwood Plaza", site_type="parking", model="Pulse AC 22"),
    dict(serial="EVSE-006", name="Harbor Freight Yard", site_type="remote", model="GridLink AC 7"),
    dict(serial="EVSE-007", name="Metro Transit Depot", site_type="garage", model="VoltHub DC 350"),
    dict(serial="EVSE-008", name="Tech Campus Garage", site_type="garage", model="Pulse AC 22"),
    dict(serial="EVSE-009", name="Summit Ridge Stop", site_type="remote", model="QuadCore DC 150"),
    dict(serial="EVSE-010", name="Oakdale Transfer", site_type="remote", model="GridLink AC 7"),
    dict(serial="EVSE-011", name="Civic Center Deck", site_type="parking", model="VoltHub DC 350"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class StationSim:
    serial: str
    name: str = ""
    site_type: str = "garage"
    model: str = "VoltHub DC 350"
    rng: Random = field(default_factory=Random)

    status: str = "AVAILABLE"
    meter_kwh: float = 0.0
    temperature_c: float = 24.0
    humidity_pct: float = 50.0
    vibration_mm_s: float = 0.5
    load_kw: float = 0.0

    rate_kw: float = 6.0
    session: dict | None = None
    transition_in: float = 0.0

    def __post_init__(self) -> None:
        self.rate_kw = self.rng.uniform(7.0, 30.0) if "350" in self.model else self.rng.uniform(3.5, 7.5)
        self.meter_kwh = self.rng.uniform(300, 4000)

    def connect(self) -> str:
        if "350" in self.model:
            return self.rng.choice(["CCS1", "CCS2", "CHAdeMO"])
        return "CCS2"

    def tick(self, dt: float, ts: str) -> tuple[dict, list[dict]]:
        """Advance one sample. dt is simulated elapsed seconds. Returns (sample, events)."""
        events: list[dict] = []
        rng = self.rng
        dt_hours = dt / 3600.0

        # --- status transitions -------------------------------------------
        if self.status == "OFFLINE":
            self.transition_in -= 1
            if self.transition_in <= 0:
                self._set_status("AVAILABLE", ts, events, reason="link restored")
        elif self.status == "FAULTED":
            self.transition_in -= 1
            if self.transition_in <= 0:
                self._set_status("MAINTENANCE", ts, events, reason="fault diagnosed")
        elif self.status == "MAINTENANCE":
            self.transition_in -= 1
            if self.transition_in <= 0:
                self._set_status("AVAILABLE", ts, events)
        elif self.status == "AVAILABLE":
            roll = rng.random()
            if roll < 0.0015:
                self._set_status("OFFLINE", ts, events, reason="link loss")
                self.transition_in = rng.randint(2, 8)
            elif roll < 0.0055:
                self._set_status("FAULTED", ts, events, reason=f"fault E{rng.randint(10, 42)}")
                self.transition_in = rng.randint(3, 12)
            elif roll < 0.17:
                self.session = {
                    "start_ts": ts,
                    "connector": self.connect(),
                    "start_meter": self.meter_kwh,
                    "id": uuid4().hex,
                }
                self._set_status("CHARGING", ts, events)
                events.append(
                    {
                        "station_id": self.serial,
                        "event": "start",
                        "ts": ts,
                        "connector": self.session["connector"],
                        "session_id": self.session["id"],
                        "start_meter_kwh": round(self.session["start_meter"], 3),
                    }
                )
        elif self.status == "CHARGING":
            self.load_kw = self.rate_kw * rng.uniform(0.8, 1.0)
            self.meter_kwh += self.load_kw * dt_hours
            if rng.random() < 0.09:
                s = self.session
                if s:
                    delivery = self.meter_kwh - s["start_meter"]
                    events.append(
                        {
                            "station_id": self.serial,
                            "event": "end",
                            "ts": ts,
                            "connector": s["connector"],
                            "session_id": s["id"],
                            "end_meter_kwh": round(self.meter_kwh, 3),
                            "kwh": round(delivery, 3),
                        }
                    )
                self.session = None
                self.load_kw = 0.0
                self._set_status("AVAILABLE", ts, events)

        # --- sensor dynamics ----------------------------------------------
        if self.status == "FAULTED":
            temp_target = 60.0 + rng.uniform(0, 15)
            vib = self.vibration_mm_s
            self.vibration_mm_s = physics.walk(vib, rng.uniform(12, 16), 0.3, 1.0, rng, 0, 20)
            self.load_kw = 0.0
        elif self.status == "CHARGING":
            temp_target = 26.0 + (self.load_kw / self.rate_kw) * 22.0
            self.vibration_mm_s = physics.walk(self.vibration_mm_s, 1.5 + self.load_kw * 0.12, 0.3, 0.6, rng, 0, 20)
        else:
            temp_target = 24.0 + (0.5 if self.site_type == "remote" else 0.0)
            self.vibration_mm_s = physics.walk(self.vibration_mm_s, 0.4, 0.4, 0.3, rng, 0, 20)

        self.temperature_c = physics.temperature(temp_target, self.temperature_c, rng)
        self.humidity_pct = physics.humidity(self.humidity_pct, rng)

        sample = {
            "station_id": self.serial,
            "ts": ts,
            "status": self.status,
            "meter_kwh": round(self.meter_kwh, 3),
            "temperature_c": round(self.temperature_c, 2),
            "humidity_pct": round(self.humidity_pct, 2),
            "vibration_mm_s": round(self.vibration_mm_s, 3),
            "load_kw": round(self.load_kw, 2),
        }
        return sample, events

    def _set_status(self, status: str, ts: str, events: list[dict], reason: str | None = None) -> None:
        if status == self.status:
            return
        self.status = status