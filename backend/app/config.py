from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

COLLECTIONS = ("stations", "telemetry", "sessions", "workorders", "manuals", "technicians")

STATION_STATUSES = ("AVAILABLE", "CHARGING", "FAULTED", "MAINTENANCE", "OFFLINE")
WORKORDER_STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
CONNECTORS = ("CCS1", "CCS2", "CHAdeMO", "TYPE2")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVSE_", env_file=".env", extra="ignore")

    cb_host: str = "localhost"
    cb_username: str = "Administrator"
    cb_password: str = "password"
    bucket: str = "fleetops"
    scope: str = "_default"
    version: str = "0.1.0"

    # Attempt schema + seed provisioning on startup (harmless if already done).
    bootstrap_on_startup: bool = True
    seed_on_startup: bool = True

    telemetry_ttl_days: int = 7
    sse_retry_ms: int = 3000

    @property
    def connection_string(self) -> str:
        return f"couchbase://{self.cb_host}"

    @property
    def collection_names(self) -> tuple[str, ...]:
        return COLLECTIONS


@lru_cache
def get_settings() -> Settings:
    return Settings()