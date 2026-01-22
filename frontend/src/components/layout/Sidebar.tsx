import React from "react";
import { HealthStatus } from "../../types";

const sections = [
  { id: "overview", label: "Обзор" },
  { id: "rentals", label: "Активные аренды" },
  { id: "inventory", label: "Инвентарь" },
  { id: "lots", label: "Лоты" },
  { id: "chats", label: "Чаты FunPay" },
  { id: "manage", label: "Управление аккаунтом" },
  { id: "add", label: "Добавить аккаунт" },
  { id: "notifications", label: "Уведомления" },
  { id: "settings", label: "Настройки" },
];

const healthLabel = (status: HealthStatus | null) => {
  if (status?.funpay_ready) return "FunPay готов";
  if (status?.funpay_enabled) return "FunPay запускается";
  return "FunPay отключен";
};

type SidebarProps = {
  health: HealthStatus | null;
  onRefreshAll: () => void;
};

const Sidebar: React.FC<SidebarProps> = ({ health, onRefreshAll }) => {
  return (
    <aside className="sticky top-0 h-screen w-full max-w-[260px] border-r border-slate-900 bg-slate-950/80 p-6 backdrop-blur">
      <div className="text-xl font-semibold">FunpaySeller</div>
      <p className="mt-2 text-sm text-slate-400">
        Автоматизация аренды FunPay и Steam-инструменты.
      </p>
      <nav className="mt-6 flex flex-col gap-2 text-sm">
        {sections.map((section) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            className="rounded-xl px-3 py-2 text-slate-300 transition hover:bg-slate-900 hover:text-white"
          >
            {section.label}
          </a>
        ))}
      </nav>
      <div className="mt-6 rounded-2xl border border-slate-800 bg-panel/80 p-4">
        <p className="text-xs uppercase tracking-wide text-slate-400">Статус</p>
        <div className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          {healthLabel(health)}
        </div>
        <button className="btn-ghost mt-4 w-full" onClick={onRefreshAll}>
          Обновить все
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
