import { useEffect, useState } from "react";
import { getManuals } from "../api/client";
import type { Manual } from "../types";

export function Manuals() {
  const [manuals, setManuals] = useState<Manual[]>([]);
  const [model, setModel] = useState<string>("");

  useEffect(() => {
    getManuals(model || undefined).then(setManuals).catch(() => undefined);
  }, [model]);

  const models = [...new Set(manuals.map((m) => m.model))];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold text-slate-100">Service manuals</h2>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="ml-auto rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm"
        >
          <option value="">All models</option>
          {models.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {manuals.map((m) => (
          <div key={m.key} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs font-medium uppercase tracking-wider text-slate-500">{m.model}</div>
            <div className="mt-1 text-sm font-semibold text-slate-100">{m.title}</div>
            <div className="mt-2 text-xs text-slate-500">
              Version {m.version} · synced to technician app (Couchbase Lite)
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}