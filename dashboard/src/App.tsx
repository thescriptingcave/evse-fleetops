import { useState } from "react";
import { useLiveEvents } from "./api/useLiveEvents";
import { Manuals } from "./pages/Manuals";
import { Overview } from "./pages/Overview";
import { Stations } from "./pages/Stations";
import { WorkOrders } from "./pages/WorkOrders";

type Tab = "overview" | "stations" | "workorders" | "manuals";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "stations", label: "Stations" },
  { id: "workorders", label: "Work Orders" },
  { id: "manuals", label: "Manuals" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const { events, latest } = useLiveEvents();

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">⚡</span>
            <div>
              <h1 className="text-sm font-bold leading-tight text-slate-100">EVSE FleetOps</h1>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Offline service & telemetry</p>
            </div>
          </div>
          <nav className="ml-auto flex items-center gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`rounded-lg px-3 py-1.5 text-sm transition ${
                  tab === t.id
                    ? "bg-slate-800 text-slate-100"
                    : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        {tab === "overview" && <Overview events={events} />}
        {tab === "stations" && <Stations latest={latest} />}
        {tab === "workorders" && <WorkOrders />}
        {tab === "manuals" && <Manuals />}
      </main>
    </div>
  );
}