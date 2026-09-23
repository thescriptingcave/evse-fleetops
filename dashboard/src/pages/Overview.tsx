import { useEffect, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { getFleetOverview } from "../api/client";
import { EventFeed } from "../components/EventFeed";
import { KpiCard } from "../components/KpiCard";
import type { FleetOverview, LiveEvent } from "../types";

const STATUS_COLORS: Record<string, string> = {
  AVAILABLE: "#34d399",
  CHARGING: "#38bdf8",
  FAULTED: "#f43f5e",
  MAINTENANCE: "#f59e0b",
  OFFLINE: "#64748b",
};

export function Overview({ events }: { events: LiveEvent[] }) {
  const [overview, setOverview] = useState<FleetOverview | null>(null);

  const refresh = () => {
    getFleetOverview().then(setOverview).catch(() => undefined);
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, []);

  // Status/session changes move the KPIs; plain telemetry is covered by the interval.
  const newest = events[0];
  useEffect(() => {
    if (newest && (newest.type === "status" || newest.type === "session")) refresh();
  }, [newest]);

  const totals = overview?.station_totals ?? {};
  const totalStations = Object.values(totals).reduce((a, b) => a + b, 0);
  const pie = Object.entries(totals).map(([name, value]) => ({ name, value }));

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
      <div className="space-y-4 xl:col-span-2">
        <KpiRow overview={overview} totalStations={totalStations} />

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="text-sm font-semibold text-slate-200">Fleet status</h3>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pie} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} paddingAngle={2} stroke="#0f172a">
                    {pie.map((s) => (
                      <Cell key={s.name} fill={STATUS_COLORS[s.name] ?? "#94a3b8"} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-wrap gap-2">
              {pie.map((s) => (
                <span key={s.name} className="inline-flex items-center gap-1.5 text-xs text-slate-400">
                  <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLORS[s.name] }} />
                  {s.name} · {s.value}
                </span>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-200">
              Alerts{" "}
              <span className="text-xs font-normal text-slate-500">(temperature / humidity / vibration)</span>
            </h3>
            {!overview || overview.alerts.length === 0 ? (
              <p className="text-sm text-slate-500">No active alerts.</p>
            ) : (
              <ul className="space-y-2">
                {overview.alerts.slice(0, 12).map((a, i) => (
                  <li key={i} className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2 text-xs">
                    <div className="font-medium text-rose-300">{a.station_id}</div>
                    <div className="text-slate-400">{a.reasons}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <div className="xl:col-span-1">
        <EventFeed events={events} />
      </div>
    </div>
  );
}

function KpiRow({ overview, totalStations }: { overview: FleetOverview | null; totalStations: number }) {
  const totals = overview?.station_totals ?? {};
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <KpiCard label="Stations" value={totalStations} />
      <KpiCard
        label="Charging now"
        value={totals.CHARGING ?? 0}
        sub={`${overview?.active_sessions ?? 0} active sessions`}
        accent="text-sky-300"
      />
      <KpiCard
        label="Energy today"
        value={`${(overview?.kwh_today ?? 0).toLocaleString()} kWh`}
        accent="text-emerald-300"
      />
      <KpiCard
        label="Active alerts"
        value={overview?.alerts.length ?? 0}
        accent={overview && overview.alerts.length > 0 ? "text-rose-300" : "text-slate-100"}
      />
    </div>
  );
}