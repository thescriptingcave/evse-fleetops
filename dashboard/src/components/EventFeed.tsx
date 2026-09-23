import type { LiveEvent } from "../types";

const BADGE: Record<LiveEvent["type"], string> = {
  snapshot: "bg-slate-500/20 text-slate-300",
  telemetry: "bg-sky-500/15 text-sky-300",
  status: "bg-emerald-500/15 text-emerald-300",
  session: "bg-indigo-500/15 text-indigo-300",
  alert: "bg-rose-500/15 text-rose-300",
  workorder: "bg-amber-500/15 text-amber-300",
};

export function EventFeed({ events }: { events: LiveEvent[] }) {
  const visible = events.slice(0, 40);
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-200">Live event stream</h3>
      <div className="space-y-1.5">
        {visible.length === 0 && <p className="text-sm text-slate-500">Waiting for the stream…</p>}
        {visible.map((ev, i) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <span className={`shrink-0 rounded px-1.5 py-0.5 font-medium ${BADGE[ev.type]}`}>{ev.type}</span>
            <span className="truncate text-slate-300">{describe(ev)}</span>
            <span className="ml-auto shrink-0 text-slate-500 tabular-nums">
              {ev.evt_ts ? new Date(ev.evt_ts).toLocaleTimeString() : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function describe(ev: LiveEvent): string {
  switch (ev.type) {
    case "status":
      return `${ev.station_id} → ${ev.status}${ev.reason ? ` (${ev.reason})` : ""}`;
    case "session":
      return `${ev.station_id}: session ${ev.event === "start" ? "started" : "ended"}${ev.kwh != null ? ` · ${ev.kwh} kWh` : ""}`;
    case "alert":
      return `${ev.station_id}: ${ev.reason}`;
    case "workorder":
      return `${ev.station_id}: workorder ${ev.event}${ev.workorder_id ? ` #${ev.workorder_id}` : ""}`;
    case "telemetry":
      return `${ev.station_id}: reading @ ${ev.ts ?? ""}`;
    default:
      return JSON.stringify(ev).slice(0, 120);
  }
}