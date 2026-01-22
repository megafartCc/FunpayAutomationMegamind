import React from "react";
import { Stats } from "../../types";

const StatCard: React.FC<{ label: string; value: number | string }> = ({ label, value }) => (
  <div className="card">
    <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
    <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
  </div>
);

type StatsOverviewProps = {
  stats: Stats | null;
};

const StatsOverview: React.FC<StatsOverviewProps> = ({ stats }) => {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Всего аккаунтов" value={stats?.total_accounts ?? 0} />
      <StatCard label="Активные аренды" value={stats?.active_rentals ?? 0} />
      <StatCard label="Свободные" value={stats?.available_accounts ?? 0} />
      <StatCard label="За 24 часа" value={stats?.recent_rentals ?? 0} />
    </div>
  );
};

export default StatsOverview;
