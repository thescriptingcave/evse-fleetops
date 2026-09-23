import { useEffect, useState } from "react";
import {
  addWorkOrderNote,
  createWorkOrder,
  getStations,
  listWorkOrders,
  updateWorkOrder,
} from "../api/client";
import type { Priority, Station, WorkOrder, WorkOrderStatus } from "../types";

const PRIORITY_BADGE: Record<Priority, string> = {
  LOW: "bg-slate-500/15 text-slate-300",
  MEDIUM: "bg-sky-500/15 text-sky-300",
  HIGH: "bg-amber-500/15 text-amber-300",
  CRITICAL: "bg-rose-500/15 text-rose-300",
};

export function WorkOrders() {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [stations, setStations] = useState<Station[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    listWorkOrders({ status: statusFilter || undefined })
      .then(setOrders)
      .catch(() => undefined);
  };

  useEffect(() => {
    refresh();
    getStations().then(setStations).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const onCreate = async (form: { station_id: string; title: string; priority: Priority; description?: string }) => {
    setError(null);
    try {
      await createWorkOrder(form);
      setCreating(false);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          {(["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"] as WorkOrderStatus[]).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button
          onClick={() => setCreating(true)}
          className="rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-emerald-950 hover:bg-emerald-400"
        >
          + New work order
        </button>
        {error && <span className="text-xs text-rose-300">{error}</span>}
      </div>

      {creating && <CreateWorkOrder stations={stations} onCancel={() => setCreating(false)} onSubmit={onCreate} />}

      <div className="overflow-hidden rounded-xl border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-3">ID</th>
              <th className="px-4 py-3">Station</th>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Assignee</th>
              <th className="px-4 py-3">Updated</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/40">
            {orders.map((wo) => (
              <WorkOrderRow key={wo.id} wo={wo} onChanged={refresh} />
            ))}
            {orders.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-slate-500">
                  No work orders
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WorkOrderRow({ wo, onChanged }: { wo: WorkOrder; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [author, setAuthor] = useState("ops-desk");

  const setStatus = (status: WorkOrderStatus) =>
    updateWorkOrder(wo.id, { status }).then(onChanged).catch(() => undefined);

  const submitNote = async () => {
    if (!note.trim()) return;
    await addWorkOrderNote(wo.id, { author, text: note.trim() });
    setNote("");
    onChanged();
  };

  return (
    <>
      <tr className="hover:bg-slate-800/40">
        <td className="px-4 py-3 font-mono text-xs text-slate-400">{wo.id.slice(0, 8)}</td>
        <td className="px-4 py-3 text-slate-200">{wo.station_id}</td>
        <td className="px-4 py-3 font-medium text-slate-100">{wo.title}</td>
        <td className="px-4 py-3">
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${PRIORITY_BADGE[wo.priority]}`}>{wo.priority}</span>
        </td>
        <td className="px-4 py-3">
          <select
            value={wo.status}
            onChange={(e) => setStatus(e.target.value as WorkOrderStatus)}
            className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-xs"
          >
            {(["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"] as WorkOrderStatus[]).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </td>
        <td className="px-4 py-3 text-slate-400">{wo.assignee ?? "—"}</td>
        <td className="px-4 py-3 text-xs tabular-nums text-slate-500">
          {new Date(wo.updated_ts).toLocaleString()}
        </td>
        <td className="px-4 py-3">
          <button onClick={() => setOpen(!open)} className="rounded px-2 py-1 text-xs text-slate-400 hover:text-slate-200">
            {open ? "Hide" : `${wo.notes.length} notes`}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="bg-slate-950/60">
          <td colSpan={8} className="px-6 py-3">
            {wo.description && <p className="mb-2 text-xs text-slate-400">{wo.description}</p>}
            <ul className="space-y-1.5">
              {wo.notes.map((n, i) => (
                <li key={i} className="text-xs">
                  <span className="font-medium text-slate-300">{n.author}</span>{" "}
                  <span className="text-slate-400">· {new Date(n.ts).toLocaleString()}</span>
                  <div className="text-slate-300">{n.text}</div>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-center gap-2">
              <input
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                className="w-32 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs"
                placeholder="author"
              />
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitNote()}
                className="flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs"
                placeholder="Add a technician note…"
              />
              <button
                onClick={submitNote}
                className="rounded-lg bg-slate-700 px-3 py-1 text-xs text-slate-100 hover:bg-slate-600"
              >
                Add note
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function CreateWorkOrder({
  stations,
  onCancel,
  onSubmit,
}: {
  stations: Station[];
  onCancel: () => void;
  onSubmit: (f: { station_id: string; title: string; priority: Priority; description?: string }) => void;
}) {
  const [stationId, setStationId] = useState(stations[0]?.serial ?? "");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState<Priority>("MEDIUM");
  const [description, setDescription] = useState("");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (stationId && title.trim()) onSubmit({ station_id: stationId, title: title.trim(), priority, description: description.trim() || undefined });
      }}
      className="space-y-3 rounded-xl border border-slate-700 bg-slate-900 p-4"
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className="text-xs text-slate-400">
          Station
          <select
            value={stationId}
            onChange={(e) => setStationId(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
            required
          >
            {stations.map((s) => (
              <option key={s.serial} value={s.serial}>
                {s.serial} · {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Priority
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value as Priority)}
            className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
          >
            {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as Priority[]).map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="block text-xs text-slate-400">
        Title
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
          required
        />
      </label>
      <label className="block text-xs text-slate-400">
        Description
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
        />
      </label>
      <div className="flex items-center gap-2">
        <button type="submit" className="rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-emerald-950 hover:bg-emerald-400">
          Create
        </button>
        <button type="button" onClick={onCancel} className="rounded-lg px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200">
          Cancel
        </button>
      </div>
    </form>
  );
}