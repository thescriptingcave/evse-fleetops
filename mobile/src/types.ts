// Copied from the dashboard's type model (kept in sync by hand).
// In a real repo these would be shared via a workspace package.

export type StationStatus = "AVAILABLE" | "CHARGING" | "FAULTED" | "MAINTENANCE" | "OFFLINE";
export type Priority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type WorkOrderStatus = "OPEN" | "IN_PROGRESS" | "RESOLVED" | "CLOSED";

export interface Station {
  serial: string;
  name: string;
  site_type: string;
  model: string;
  status: StationStatus;
  firmware: string;
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

export interface SyncStatus {
  mode: "couchbase-lite" | "mock";
  replicator: "stopped" | "offline" | "connecting" | "idle" | "active";
  progress: number; // 0..1
  pending: number;
  lastSync: string | null;
}