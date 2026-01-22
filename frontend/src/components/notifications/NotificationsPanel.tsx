import React from "react";
import { NotificationItem } from "../../types";
import { formatDate } from "../../utils/format";

const NotificationsPanel: React.FC<{ notifications: NotificationItem[] }> = ({ notifications }) => {
  if (!notifications.length) {
    return (
      <div className="panel">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h4 className="text-sm font-semibold">Уведомлений нет</h4>
          <p className="text-xs text-slate-400">Системные события появятся здесь.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="panel space-y-4">
      {notifications.map((item, index) => (
        <div key={`${item.created_at}-${index}`} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h4 className="text-sm font-semibold">
            {(item.level || "инфо").toUpperCase()} - {formatDate(item.created_at || "")}
          </h4>
          <p className="mt-2 text-sm text-slate-200">{item.message}</p>
          <p className="mt-2 text-xs text-slate-400">
            Владелец: {item.owner || "-"} | Аккаунт: {item.account_id || "-"}
          </p>
        </div>
      ))}
    </div>
  );
};

export default NotificationsPanel;
