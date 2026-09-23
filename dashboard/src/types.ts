export type StationStatus = "AVAILABLE" | "CHARGING" | "FAULTED" | "MAINTENANCE" | "OFFLINE";
export type Priority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type WorkOrderStatus = "OPEN" | "IN_PROGRESS" | "RESOLVED" | "CLOSED";

export interface LatestReading {
  station_id: string;
  ts: string;
  status: StationStatus;
  meter_kwh: number;
  temperature_c: number | null;
  humidity_pct: number | null;
  vibration_mm_s: number | null;
  load_kw: number | null;
}

export interface Station {
  serial: string;
  name: string;
  site_type: string;
  model: string;
  lat: number;
  lon: number;
  status: StationStatus;
  firmware: string;
  meter_kwh: number | null;
  temperature_c: number | null;
  last_seen: string | null;
  last_status_reason?: string;
  latest?: LatestReading | null;
}

export interface WorkOrderNote {
  author: string;
  text: string;
  ts: string;
}

export interface WorkOrder {
  id: string;
  station_id: string;
  title: string;
  description?: string | null;
  priority: Priority;
  status: WorkOrderStatus;
  assignee?: string | null;
  notes: WorkOrderNote[];
  created_ts: string;
  updated_ts: string;
}

export interface Manual {
  key: string;
  model: string;
  title: string;
  version: string;
}

export interface Session {
  id: string;
  station_id: string;
  connector: string;
  start_ts: string;
  end_ts: string | null;
  state: string;
  kwh_delivered: number;
}

export interface FleetOverview {
  station_totals: Record<string, number>;
  active_sessions: number;
  alerts: { station_id: string; reasons: string; ts: string }[];
  kwh_today: number;
  last_updated: string | null;
}

export type LiveEventType = "snapshot" | "telemetry" | "status" | "session" | "alert" | "workorder";

export interface LiveEvent {
  type: LiveEventType;
  evt_ts?: string;
  station_id?: string;
  status?: StationStatus;
  ts?: string;
  reason?: string;
  event?: string;
  kwh?: number;
  session_id?: string;
  temperature_c?: number;
  humidity_pct?: number;
  vibration_mm_s?: number;
  meter_kwh?: number;
  load_kw?: number;
  workorder_id?: string;
  latest?: Record<string, LatestReading>;
  recent?: LiveEvent[];
}

export interface TimeseriesPoint {
  ts_ms: number;
  value: number;
}

export interface TimeseriesResponse {
  serial: string;
  metric: string;
  bucket_minutes: number;
  points: TimeseriesPoint[];
}