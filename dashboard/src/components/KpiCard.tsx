export function KpiCard({
  label,
  value,
  sub,
  accent = "text-slate-100",
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1.5 text-2xl font-semibold tabular-nums ${accent}`}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-500">{sub}</div> : null}
    </div>
  );
}