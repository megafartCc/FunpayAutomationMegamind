import React from "react";
import { Rental } from "../../types";
import {
  formatDate,
  formatDuration,
  formatRentalEnd,
  formatRemainingSeconds,
  getDurationMinutes,
  getRentalEndTimestamp,
  presenceLabel,
} from "../../utils/format";

const PRESENCE_BASE_URL =
  (import.meta.env.VITE_PRESENCE_URL && import.meta.env.VITE_PRESENCE_URL.replace(/\/$/, "")) ||
  (typeof window !== "undefined" && (window as any).__PRESENCE_URL__?.replace?.(/\/$/, "")) ||
  "https://laudable-flow-production-9c8a.up.railway.app/presence";

type ActiveRentalsTableProps = {
  rentals: Rental[];
  tick: number;
  matchStartCache: React.MutableRefObject<Map<string, number>>;
};

const getMatchSecondsForItem = (item: Rental) => {
  const rawSeconds = Number(item?.match_seconds);
  if (!Number.isFinite(rawSeconds)) return null;
  return Math.max(0, Math.floor(rawSeconds));
};

const ActiveRentalsTable: React.FC<ActiveRentalsTableProps> = ({ rentals, tick, matchStartCache }) => {
  void tick;
  void matchStartCache;

  if (!rentals.length) {
    return (
      <div className="panel">
        <p className="text-sm text-slate-400">Нет активных аренд.</p>
      </div>
    );
  }

  return (
    <div className="panel overflow-x-auto">
      <table className="table min-w-[980px]">
        <thead>
          <tr>
            <th>ID</th>
            <th>Аккаунт</th>
            <th>Покупатель</th>
            <th>Чат</th>
            <th>Логин</th>
            <th>Начало</th>
            <th>Окончание</th>
            <th>Осталось</th>
            <th>Длительность</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          {rentals.map((item) => {
            const matchSeconds = getMatchSecondsForItem(item);
            const rentalEnd = getRentalEndTimestamp(item);
            const remainingSeconds = Number.isFinite(rentalEnd)
              ? Math.max(0, Math.floor(((rentalEnd ?? 0) - now) / 1000))
              : null;
            const label = presenceLabel(item, matchSeconds);
            const presenceUrl = item.steamid ? `${PRESENCE_BASE_URL}/${item.steamid}` : null;
            return (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.account_name}</td>
                <td>{item.owner}</td>
                <td>
                  {item.chat_url ? (
                    <a className="text-amber-300" href={item.chat_url} target="_blank" rel="noreferrer">
                      {item.chat_url}
                    </a>
                  ) : (
                    "-"
                  )}
                </td>
                <td>{item.login}</td>
                <td>{formatDate(item.rental_start)}</td>
                <td>{formatRentalEnd(item.rental_start || undefined, getDurationMinutes(item))}</td>
                <td>{formatRemainingSeconds(remainingSeconds)}</td>
                <td>{formatDuration(item)}</td>
                <td>
                  {presenceUrl ? (
                    <a className="text-amber-300" href={presenceUrl} target="_blank" rel="noreferrer">
                      {label}
                    </a>
                  ) : (
                    label
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default ActiveRentalsTable;
