import { useEffect, useMemo, useState } from "react";
import { getStations, patchStation } from "../api/client";
import { StatusChip } from "../components/StatusChip";
import { TimeseriesPanel } from "../components/TimeseriesPanel";
import type { LatestReading, Station, StationStatus } from "../types";

export function Stations({ latest }: { latest: Record<string, LatestReading> | null }) {
  const [stations, setStations] = useState<Station[]>([]);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selected, setSelected] = useState<string | null>(null);

  const fetchStations = () => {
    getStations({ q: q || undefined, status: statusFilter || undefined })
      .then(setStations)
      .catch(() => undefined);
  };

  useEffect(() => {
    const t = setTimeout(fetchStations, 150);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, statusFilter]);

  // keep cards live as readings stream in
  const enriched = useMemo(
    () => stations.map((s) => ({ ...s, latest: latest?.[s.serial] ?? s.latest })),
    [stations, latest],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name or serial…"
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-500"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100"
        >
          <option value="">All statuses</option>
          {(["AVAILABLE", "CHARGING", "FAULTED", "MAINTENANCE", "OFFLINE"] as StationStatus[]).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <span className="text-xs text-slate-500">{enriched.length} stations</span>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {enriched.map((s) => {
          const r = s.latest;
          return (
            <div
              key={s.serial}
              onClick={() => setSelected(selected === s.serial ? null : s.serial)}
              className="cursor-pointer rounded-xl border border-slate-800 bg-slate-900/60 p-4 transition hover:border-slate-600"
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="truncate text-sm font-semibold text-slate-100">{s.name}</h3>
                <StatusChip status={(r?.status ?? s.status) as StationStatus} pulse={r?.status === "CHARGING"} />
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {s.serial} · {s.model} · {s.site_type}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 border-t border-slate-800 pt-3 text-xs">
                <Metric label="Temp" value={fmt(r?.temperature_c, "°C")} />
                <Metric label="Hum" value={fmt(r?.humidity_pct, "%")} />
                <Metric label="Vib" value={fmt(r?.vibration_mm_s, "mm/s")} />
              </div>
              <div className="mt-2 text-xs text-slate-500">Meter {fmt(r?.meter_kwh, " kWh")}</div>
              {s.last_status_reason && (
                <div className="mt-2 rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-300">{s.last_status_reason}</div>
              )}
            </div>
          );
        })}
      </div>

      {selected && (
        <div className="space-y-4 border-t border-slate-800 pt-4">
          <StationControl serial={selected} onClose={() => setSelected(null)} />
          <TimeseriesPanel serial={selected} />
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-0.5 font-medium tabular-nums text-slate-200">{value}</div>
    </div>
  );
}

function fmt(v: number | null | undefined, unit: string): string {
  return v == null ? "—" : `${v.toFixed(1)}${unit}`;
}

function StationControl({ serial, onClose }: { serial: string; onClose: () => void }) {
  const setStatus = (status: StationStatus) =>
    patchStation(serial, { status, reason: "operator override" })
      .then(() => undefined)
      .catch(() => undefined);
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-sm">
      <span className="font-semibold text-slate-200">Operator control · {serial}</span>
      {(["MAINTENANCE", "AVAILABLE"] as StationStatus[]).map((s) => (
        <button
          key={s}
          onClick={() => setStatus(s)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
        >
          Set {s}
        </button>
      ))}
      <button onClick={onClose} className="ml-auto rounded-lg px-2 py-1 text-xs text-slate-500 hover:text-slate-300">
        Close ▲
      </button>
    </div>
  );
}