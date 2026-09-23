import { useState, useEffect } from "react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { getTimeseries } from "../api/client";
import type { TimeseriesResponse } from "../types";

const METRICS: { key: string; label: string; color: string }[] = [
  { key: "temperature_c", label: "Temperature (°C)", color: "#f59e0b" },
  { key: "humidity_pct", label: "Humidity (%)", color: "#38bdf8" },
  { key: "vibration_mm_s", label: "Vibration (mm/s)", color: "#a78bfa" },
  { key: "meter_kwh", label: "Meter (kWh)", color: "#34d399" },
];

export function TimeseriesPanel({ serial }: { serial: string }) {
  const [metric, setMetric] = useState("temperature_c");
  const [bucket, setBucket] = useState(5);
  const [data, setData] = useState<TimeseriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    setError(null);
    const to = new Date().toISOString();
    const from = new Date(Date.now() - 6 * 3600_000).toISOString();
    getTimeseries(serial, metric, bucket, from, to)
      .then(setData)
      .catch((e) => setError(String(e)));
  };

  useEffect(refresh, [serial, metric, bucket]);

  const points = data?.points.map((p) => ({
    time: new Date(p.ts_ms).toLocaleTimeString(),
    value: p.value,
  })) ?? [];

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-200">Reading history · {serial}</h3>
        <div className="flex items-center gap-2">
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200"
          >
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
          <select
            value={bucket}
            onChange={(e) => setBucket(Number(e.target.value))}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200"
          >
            <option value={1}>1 min</option>
            <option value={5}>5 min</option>
            <option value={15}>15 min</option>
            <option value={60}>60 min</option>
          </select>
        </div>
      </div>

      {error ? (
        <p className="mt-4 text-sm text-rose-300">{error}</p>
      ) : data === null ? (
        <p className="mt-4 text-sm text-slate-500">Loading history…</p>
      ) : points.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">No data in window yet.</p>
      ) : (
        <div className="mt-3 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 11 }} tickLine={false} />
              <YAxis tick={{ fill: "#64748b", fontSize: 11 }} tickLine={false} domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                labelStyle={{ color: "#cbd5e1" }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={METRICS.find((m) => m.key === metric)?.color ?? "#34d399"}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}