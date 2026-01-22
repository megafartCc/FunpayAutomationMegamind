import React, { useState } from "react";
import { Account, Lot } from "../../types";

export type LotsPanelProps = {
  lots: Lot[];
  accounts: Account[];
  onCreate: (payload: { lot_number: number; account_id: number; lot_url?: string | null }) => Promise<void>;
  onDelete: (lotNumber: number) => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

const LotsPanel: React.FC<LotsPanelProps> = ({ lots, accounts, onCreate, onDelete, onToast }) => {
  const [lotNumber, setLotNumber] = useState("");
  const [accountId, setAccountId] = useState("");
  const [lotUrl, setLotUrl] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const number = Number(lotNumber);
    const account = Number(accountId);
    if (!number || !account) {
      onToast("Укажите номер лота и аккаунт.", true);
      return;
    }
    try {
      await onCreate({ lot_number: number, account_id: account, lot_url: lotUrl.trim() || null });
      setLotNumber("");
      setAccountId("");
      setLotUrl("");
      onToast("Лот сохранен.");
    } catch (error) {
      onToast((error as Error).message || "Не удалось сохранить лот", true);
    }
  };

  return (
    <div className="panel space-y-6">
      <form className="grid gap-4 lg:grid-cols-[120px_1fr_1fr_auto]" onSubmit={handleSubmit}>
        <div>
          <label className="field-label">Номер лота</label>
          <input
            className="input"
            type="number"
            min={1}
            value={lotNumber}
            onChange={(event) => setLotNumber(event.target.value)}
            required
          />
        </div>
        <div>
          <label className="field-label">Аккаунт</label>
          <select
            className="input"
            value={accountId}
            onChange={(event) => setAccountId(event.target.value)}
            required
          >
            <option value="">Выберите аккаунт</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.account_name} (ID {account.id})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">Ссылка на лот</label>
          <input
            className="input"
            type="url"
            value={lotUrl}
            onChange={(event) => setLotUrl(event.target.value)}
            placeholder="https://funpay.com/lots/81/..."
          />
        </div>
        <div className="flex items-end">
          <button className="btn" type="submit">
            Сохранить
          </button>
        </div>
      </form>

      <div className="overflow-x-auto">
        <table className="table min-w-[640px]">
          <thead>
            <tr>
              <th>Лот</th>
              <th>Аккаунт</th>
              <th>Ссылка</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {lots.length ? (
              lots.map((lot) => (
                <tr key={lot.lot_number}>
                  <td>№{lot.lot_number}</td>
                  <td>
                    {lot.account_name} (ID {lot.account_id})
                  </td>
                  <td>
                    {lot.lot_url ? (
                      <a className="text-amber-300" href={lot.lot_url} target="_blank" rel="noreferrer">
                        {lot.lot_url}
                      </a>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td>
                    <button
                      className="btn-ghost"
                      type="button"
                      onClick={() => onDelete(lot.lot_number)}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4}>Лоты не настроены.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default LotsPanel;
