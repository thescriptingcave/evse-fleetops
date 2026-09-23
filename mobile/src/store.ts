import type { Manual, Station, SyncStatus, WorkOrder } from "./types";

/**
 * Offline-first data access layer.
 *
 * Two backends:
 *  - "mock": in-memory seed data. Runs anywhere (Expo Go), no native deps.
 *  - "couchbase-lite": real local Couchbase Lite DB + bidirectional Sync
 *    Gateway replication. Requires a native dev-client build (see
 *    docs/mobile-status.md). `push/pull` continuously replicate in the
 *    background; edits made while disconnected are queued and replayed on
 *    reconnect with automatic conflict resolution.
 */

export interface FleetStore {
  readonly mode: string;
  listStations(): Promise<Station[]>;
  listWorkOrders(): Promise<WorkOrder[]>;
  getWorkOrder(id: string): Promise<WorkOrder | null>;
  createWorkOrder(input: Partial<WorkOrder>): Promise<WorkOrder>;
  patchWorkOrder(id: string, patch: Partial<WorkOrder>): Promise<WorkOrder>;
  addNote(id: string, author: string, text: string): Promise<WorkOrder>;
  listManuals(): Promise<Manual[]>;
  syncStatus(): Promise<SyncStatus>;
}

const MOCK_STATIONS: Station[] = [
  { serial: "EVSE-002", name: "Airport P2 Level 1", site_type: "parking", model: "QuadCore DC 150", status: "AVAILABLE", firmware: "4.12.6" },
  { serial: "EVSE-003", name: "Airport P2 Level 2", site_type: "parking", model: "QuadCore DC 150", status: "CHARGING", firmware: "4.12.6" },
  { serial: "EVSE-007", name: "Metro Transit Depot", site_type: "garage", model: "VoltHub DC 350", status: "MAINTENANCE", firmware: "4.12.6" },
  { serial: "EVSE-009", name: "Summit Ridge Stop", site_type: "remote", model: "QuadCore DC 150", status: "OFFLINE", firmware: "4.10.1" },
];

const MOCK_MANUALS: Manual[] = [
  { key: "volt-hub-350", model: "VoltHub DC 350", title: "VoltHub DC 350 Installation & Service Manual", version: "3.2.1" },
  { key: "quad-core-150", model: "QuadCore DC 150", title: "QuadCore DC 150 Maintenance Guide", version: "1.9.0" },
];

class MockStore implements FleetStore {
  readonly mode = "mock";
  private workOrders: WorkOrder[] = [
    {
      id: "sample-0",
      station_id: "EVSE-007",
      title: "Replacement of connector latch assembly",
      priority: "HIGH",
      status: "IN_PROGRESS",
      assignee: "tech_garcia",
      notes: [{ author: "tech_garcia", text: "Connector latch worn; kit ordered.", ts: new Date().toISOString() }],
      created_ts: new Date().toISOString(),
      updated_ts: new Date().toISOString(),
    },
  ];

  async listStations() {
    return MOCK_STATIONS;
  }
  async listWorkOrders() {
    return [...this.workOrders];
  }
  async getWorkOrder(id: string) {
    return this.workOrders.find((w) => w.id === id) ?? null;
  }
  async createWorkOrder(input: Partial<WorkOrder>) {
    const wo: WorkOrder = {
      id: `mock-${Date.now()}`,
      station_id: input.station_id ?? "UNKNOWN",
      title: input.title ?? "Untitled",
      priority: input.priority ?? "MEDIUM",
      status: "OPEN",
      notes: [],
      created_ts: new Date().toISOString(),
      updated_ts: new Date().toISOString(),
    };
    this.workOrders.unshift(wo);
    return wo;
  }
  async patchWorkOrder(id: string, patch: Partial<WorkOrder>) {
    const wo = await this.getWorkOrder(id);
    if (!wo) throw new Error("not found");
    Object.assign(wo, patch, { updated_ts: new Date().toISOString() });
    return wo;
  }
  async addNote(id: string, author: string, text: string) {
    const wo = await this.getWorkOrder(id);
    if (!wo) throw new Error("not found");
    wo.notes.push({ author, text, ts: new Date().toISOString() });
    wo.updated_ts = new Date().toISOString();
    return wo;
  }
  async listManuals() {
    return MOCK_MANUALS;
  }
  async syncStatus(): Promise<SyncStatus> {
    return { mode: "mock", replicator: "stopped", progress: 0, pending: 0, lastSync: null };
  }
}

export async function openFleetStore(): Promise<FleetStore> {
  // Toggle to "couchbase-lite" after producing a native dev-client build.
  const useCouchbaseLite = process.env.EXPO_PUBLIC_USE_COUCHBASE_LITE === "1";
  if (useCouchbaseLite) {
    const { createCblStore } = await import("./db/database");
    return createCblStore();
  }
  return new MockStore();
}