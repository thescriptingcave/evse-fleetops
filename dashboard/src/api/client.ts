import type {
  FleetOverview,
  LatestReading,
  Manual,
  Priority,
  Session,
  Station,
  StationStatus,
  TimeseriesResponse,
  WorkOrder,
} from "../types";

const BASE = "/api";

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} on ${path}`);
  }
  return (await res.json()) as T;
}

export const getStations = (params: { status?: string; q?: string } = {}) => {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.q) qs.set("q", params.q);
  return fetchJson<Station[]>(`/stations${qs.size ? `?${qs}` : ""}`);
};

export const getStation = (serial: string) => fetchJson<Station>(`/stations/${serial}`);

export const getTimeseries = (
  serial: string,
  metric: string,
  bucketMinutes = 5,
  from?: string,
  to?: string,
) => {
  const qs = new URLSearchParams({ metric, bucket_minutes: String(bucketMinutes) });
  if (from) qs.set("from_ts", from);
  if (to) qs.set("to_ts", to);
  return fetchJson<TimeseriesResponse>(`/stations/${serial}/timeseries?${qs}`);
};

export const getFleetOverview = () => fetchJson<FleetOverview>("/fleet/overview");

export const getLatest = () => fetchJson<{ latest: Record<string, LatestReading> }>("/telemetry/latest");

export const listWorkOrders = (params: { status?: string; station_id?: string } = {}) => {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.station_id) qs.set("station_id", params.station_id);
  return fetchJson<WorkOrder[]>(`/workorders${qs.size ? `?${qs}` : ""}`);
};

export const createWorkOrder = (payload: {
  station_id: string;
  title: string;
  description?: string;
  priority: Priority;
  assignee?: string;
}) => fetchJson<WorkOrder>("/workorders", { method: "POST", body: JSON.stringify(payload) });

export const updateWorkOrder = (id: string, payload: Partial<Pick<WorkOrder, "status" | "priority" | "assignee">>) =>
  fetchJson<WorkOrder>(`/workorders/${id}`, { method: "PUT", body: JSON.stringify(payload) });

export const addWorkOrderNote = (id: string, payload: { author: string; text: string }) =>
  fetchJson<WorkOrder>(`/workorders/${id}/notes`, { method: "POST", body: JSON.stringify(payload) });

export const patchStation = (serial: string, payload: { status: StationStatus; reason?: string }) =>
  fetchJson<Station>(`/stations/${serial}`, { method: "PATCH", body: JSON.stringify(payload) });

export const listSessions = (params: { station_id?: string } = {}) => {
  const qs = new URLSearchParams();
  if (params.station_id) qs.set("station_id", params.station_id);
  return fetchJson<Session[]>(`/sessions${qs.size ? `?${qs}` : ""}`);
};

export const getManuals = (model?: string) => {
  const qs = model ? `?model=${encodeURIComponent(model)}` : "";
  return fetchJson<Manual[]>(`/manuals${qs}`);
};