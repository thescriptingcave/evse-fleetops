// Couchbase Lite adapter (database + replicator) for the technician app.
//
// IMPORTANT: this module imports @couchbase/couchbase-lite-react-native, a
// Swift/Kotlin TurboModule. It requires a native build (Expo dev-client) and
// does NOT run in Expo Go. It is only loaded when EXPO_PUBLIC_USE_COUCHBASE_LITE=1.
//
// Written against the @couchbase/couchbase-lite-react-native 1.1.0 API
// (collection-configuration replicator API, `Replicator.create`).

import type { FleetStore } from "../store";
import type { Manual, Station, SyncStatus, WorkOrder } from "../types";

// Sync Gateway public endpoint *including the database name*. On a device or
// emulator use the host's LAN IP (Android emulator: ws://10.0.2.2:4984/fleetops).
const SYNC_ENDPOINT = process.env.EXPO_PUBLIC_SG_URL ?? "ws://127.0.0.1:4984/fleetops";
const SYNC_USER = process.env.EXPO_PUBLIC_SG_USER ?? "tech_garcia";
const SYNC_PASSWORD = process.env.EXPO_PUBLIC_SG_PASSWORD ?? "password";
const DB_NAME = "evse-technician";
const SCOPE = "_default";
const COLLECTIONS = ["stations", "workorders", "manuals"] as const;
type CollectionName = (typeof COLLECTIONS)[number];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

let opening: Promise<{ mod: Any; db: Any; colls: Record<CollectionName, Any> }> | null = null;
let replicator: Any = null;
let activity: SyncStatus["replicator"] = "stopped";
let progress = 0;
let lastSync: string | null = null;

const ACTIVITY: SyncStatus["replicator"][] = ["stopped", "offline", "connecting", "idle", "active"];

function open() {
  if (!opening) {
    opening = (async () => {
      const mod = await import("@couchbase/couchbase-lite-react-native");
      // The engine must be constructed once before any Database is created;
      // it registers itself as the native bridge for the JS API.
      new mod.CblReactNativeEngine();
      const db = new mod.Database(DB_NAME, new mod.DatabaseConfiguration());
      await db.open();
      const colls = {} as Record<CollectionName, Any>;
      for (const name of COLLECTIONS) {
        colls[name] = await db.createCollection(name, SCOPE); // returns the existing one if present
      }
      await startReplicator(mod, colls);
      return { mod, db, colls };
    })().catch((e) => {
      opening = null; // allow a retry on the next call
      throw e;
    });
  }
  return opening;
}

async function startReplicator(mod: Any, colls: Record<CollectionName, Any>): Promise<void> {
  if (replicator) return;
  const configs = COLLECTIONS.map((n) => new mod.CollectionConfiguration(colls[n]).setChannels(["fleet"]));
  const cfg = new mod.ReplicatorConfiguration(configs, new mod.URLEndpoint(SYNC_ENDPOINT));
  cfg.setReplicatorType(mod.ReplicatorType.PUSH_AND_PULL);
  cfg.setContinuous(true);
  cfg.setAuthenticator(new mod.BasicAuthenticator(SYNC_USER, SYNC_PASSWORD));

  replicator = await mod.Replicator.create(cfg);
  await replicator.addChangeListener((change: Any) => {
    const s = change.status;
    activity = ACTIVITY[s.getActivityLevel()] ?? "stopped";
    const p = s.getProgress();
    progress = p && p.getTotal() > 0 ? p.getCompleted() / p.getTotal() : activity === "idle" ? 1 : 0;
    if (activity === "idle") lastSync = new Date().toISOString();
  });
  await replicator.start(false);
}

// `SELECT META().id AS id, * FROM x AS d` yields rows shaped {id, d: {...}}.
async function queryAll<T>(db: Any, collection: CollectionName, orderBy = ""): Promise<T[]> {
  const rows: Any[] = await db
    .createQuery(`SELECT META(d).id AS id, * FROM ${SCOPE}.${collection} AS d ${orderBy}`)
    .execute();
  return rows.map((row) => ({ ...row.d, id: row.id }) as T);
}

async function saveWorkOrder(id: string, data: Record<string, unknown>): Promise<WorkOrder> {
  const { mod, colls } = await open();
  await colls.workorders.save(new mod.MutableDocument(id, data));
  return { ...(data as Omit<WorkOrder, "id">), id } as WorkOrder;
}

export function createCblStore(): FleetStore {
  const store: FleetStore = {
    mode: "couchbase-lite",
    async listStations() {
      const { db } = await open();
      return queryAll<Station>(db, "stations", "ORDER BY d.serial");
    },
    async listWorkOrders() {
      const { db } = await open();
      return queryAll<WorkOrder>(db, "workorders", "ORDER BY d.updated_ts DESC");
    },
    async getWorkOrder(id: string) {
      const { colls } = await open();
      const doc = await colls.workorders.getDocument(id);
      return doc ? ({ ...doc.toDictionary(), id } as WorkOrder) : null;
    },
    async createWorkOrder(input) {
      const now = new Date().toISOString();
      // `wo::` prefix matches the server's key scheme so the backend API can address it.
      const id = `wo::${Math.random().toString(16).slice(2)}${Date.now().toString(16)}`;
      return saveWorkOrder(id, {
        type: "workorder",
        station_id: input.station_id ?? "UNKNOWN",
        title: input.title ?? "Untitled",
        description: input.description ?? null,
        priority: input.priority ?? "MEDIUM",
        status: "OPEN",
        assignee: input.assignee ?? SYNC_USER,
        notes: [],
        created_ts: now,
        updated_ts: now,
      });
    },
    async patchWorkOrder(id: string, patch) {
      const current = await store.getWorkOrder(id);
      if (!current) throw new Error("not found");
      const { id: _ignored, ...rest } = { ...current, ...patch, updated_ts: new Date().toISOString() };
      return saveWorkOrder(id, rest);
    },
    async addNote(id: string, author: string, text: string) {
      const current = await store.getWorkOrder(id);
      if (!current) throw new Error("not found");
      const now = new Date().toISOString();
      const { id: _ignored, ...rest } = current;
      return saveWorkOrder(id, { ...rest, notes: [...(current.notes ?? []), { author, text, ts: now }], updated_ts: now });
    },
    async listManuals() {
      const { db } = await open();
      return queryAll<Manual>(db, "manuals", "ORDER BY d.model");
    },
    async syncStatus(): Promise<SyncStatus> {
      let pending = 0;
      if (replicator) {
        try {
          const { colls } = await open();
          pending = (await replicator.getPendingDocumentIds(colls.workorders)).pendingDocumentIds.length;
        } catch {
          /* not available while offline on some platforms */
        }
      }
      return { mode: "couchbase-lite", replicator: activity, progress, pending, lastSync };
    },
  };
  return store;
}
