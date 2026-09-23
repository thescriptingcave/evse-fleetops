import type { StationStatus } from "../types";

const COLORS: Record<StationStatus, string> = {
  AVAILABLE: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  CHARGING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  FAULTED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  MAINTENANCE: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  OFFLINE: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
};

const DOTS: Record<StationStatus, string> = {
  AVAILABLE: "bg-emerald-400",
  CHARGING: "bg-sky-400",
  FAULTED: "bg-rose-400",
  MAINTENANCE: "bg-amber-400",
  OFFLINE: "bg-slate-400",
};

export function StatusChip({ status, pulse = false }: { status: StationStatus; pulse?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${COLORS[status]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${DOTS[status]} ${pulse ? "animate-pulse" : ""}`} />
      {status}
    </span>
  );
}