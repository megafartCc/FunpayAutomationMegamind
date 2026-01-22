import React from "react";
import { Account } from "../../types";

const InventoryTable: React.FC<{
  accounts: Account[];
  selectedId: number | null;
  search: string;
  showPasswords: boolean;
  onSelect: (id: number) => void;
}> = ({ accounts, selectedId, search, showPasswords, onSelect }) => {
  const query = search.trim().toLowerCase();
  const filtered = accounts.filter((item) => {
    const name = item.account_name?.toLowerCase() || "";
    const login = item.login?.toLowerCase() || "";
    return !query || name.includes(query) || login.includes(query);
  });

  if (!filtered.length) {
    return (
      <div className="panel">
        <p className="text-sm text-slate-400">Аккаунты не найдены.</p>
      </div>
    );
  }

  return (
    <div className="panel overflow-x-auto">
      <table className="table min-w-[720px]">
        <thead>
          <tr>
            <th>ID</th>
            <th>Аккаунт</th>
            <th>Логин</th>
            <th>Пароль</th>
            <th>MMR</th>
            <th>SteamID</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((item) => (
            <tr
              key={item.id}
              onClick={() => onSelect(item.id)}
              className={selectedId === item.id ? "bg-slate-900" : "hover:bg-slate-900/70"}
            >
              <td>{item.id}</td>
              <td>{item.account_name}</td>
              <td>{item.login}</td>
              <td>{showPasswords ? item.password : "******"}</td>
              <td>{Number.isFinite(Number(item.mmr)) ? Number(item.mmr) : "-"}</td>
              <td>{item.steamid || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default InventoryTable;
