import React, { useEffect, useState } from "react";
import { Account } from "../../types";
import { getDurationMinutes } from "../../utils/format";

export type ManageAccountHandlers = {
  onUpdate: (payload: Record<string, unknown>) => Promise<void>;
  onAssign: (owner: string) => Promise<void>;
  onExtendOwner: (owner: string, hours: number, minutes: number) => Promise<void>;
  onRelease: () => Promise<void>;
  onExtend: (hours: number, minutes: number) => Promise<void>;
  onDeauth: () => Promise<void>;
  onChangePassword: (newPassword?: string | null) => Promise<string | null>;
  onDelete: () => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

type Props = {
  account: Account | null;
} & ManageAccountHandlers;

const ManageAccountPanel: React.FC<Props> = ({
  account,
  onUpdate,
  onAssign,
  onExtendOwner,
  onRelease,
  onExtend,
  onDeauth,
  onChangePassword,
  onDelete,
  onToast,
}) => {
  const [name, setName] = useState("");
  const [mmr, setMmr] = useState("");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [maFileJson, setMaFileJson] = useState("");
  const [durationHours, setDurationHours] = useState("");
  const [durationMinutes, setDurationMinutes] = useState("");
  const [owner, setOwner] = useState("");
  const [steamNewPassword, setSteamNewPassword] = useState("");
  const [extendHours, setExtendHours] = useState("");
  const [extendMinutes, setExtendMinutes] = useState("");
  const [extendOwnerHours, setExtendOwnerHours] = useState("");
  const [extendOwnerMinutes, setExtendOwnerMinutes] = useState("");

  useEffect(() => {
    if (!account) {
      setName("");
      setMmr("");
      setLogin("");
      setPassword("");
      setMaFileJson("");
      setDurationHours("");
      setDurationMinutes("");
      setOwner("");
      return;
    }
    setName(account.account_name || "");
    setMmr(Number.isFinite(Number(account.mmr)) ? String(account.mmr) : "");
    setLogin(account.login || "");
    setPassword(account.password || "");
    setMaFileJson("");
    const totalMinutes = getDurationMinutes(account);
    setDurationHours(totalMinutes ? String(Math.floor(totalMinutes / 60)) : "");
    setDurationMinutes(totalMinutes ? String(totalMinutes % 60) : "");
    setOwner(account.owner || "");
  }, [account]);

  const handleUpdate = async () => {
    if (!account) {
      onToast("Сначала выберите аккаунт.", true);
      return;
    }
    const payload: Record<string, unknown> = {
      account_name: name.trim(),
      login: login.trim(),
      password: password.trim(),
      mafile_json: maFileJson.trim(),
    };
    if (mmr.trim() !== "") {
      const mmrValue = Number(mmr);
      if (!Number.isFinite(mmrValue) || mmrValue < 0) {
        onToast("MMR должен быть числом 0 или выше.", true);
        return;
      }
      payload.mmr = Math.floor(mmrValue);
    }
    if (durationHours.trim() !== "" || durationMinutes.trim() !== "") {
      const hours = Number(durationHours || 0);
      const minutes = Number(durationMinutes || 0);
      if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
        onToast("Длительность должна быть числом.", true);
        return;
      }
      if (hours < 0 || minutes < 0 || minutes > 59) {
        onToast("Минуты должны быть от 0 до 59.", true);
        return;
      }
      if (hours === 0 && minutes === 0) {
        onToast("Длительность должна быть больше 0.", true);
        return;
      }
      payload.rental_duration = hours;
      payload.rental_minutes = minutes;
    }
    if (!payload.mafile_json) {
      delete payload.mafile_json;
    }
    try {
      await onUpdate(payload);
      onToast("Аккаунт обновлён.");
    } catch (error) {
      onToast((error as Error).message || "Не удалось обновить аккаунт", true);
    }
  };

  const handleAssign = async () => {
    if (!account) {
      onToast("Сначала выберите аккаунт.", true);
      return;
    }
    if (!owner.trim()) {
      onToast("Укажите владельца.", true);
      return;
    }
    try {
      await onAssign(owner.trim());
      onToast("Владелец назначен.");
    } catch (error) {
      onToast((error as Error).message || "Не удалось назначить владельца", true);
    }
  };

  const handleExtendOwner = async () => {
    if (!owner.trim()) {
      onToast("Укажите владельца.", true);
      return;
    }
    const hours = Number(extendOwnerHours || 0);
    const minutes = Number(extendOwnerMinutes || 0);
    if (extendOwnerHours === "" && extendOwnerMinutes === "") {
      onToast("Укажите часы или минуты для продления.", true);
      return;
    }
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
      onToast("Продление должно быть числом.", true);
      return;
    }
    if (hours < 0 || minutes < 0 || minutes > 59) {
      onToast("Минуты должны быть от 0 до 59.", true);
      return;
    }
    if (hours === 0 && minutes === 0) {
      onToast("Укажите часы или минуты для продления.", true);
      return;
    }
    try {
      await onExtendOwner(owner.trim(), hours, minutes);
      onToast("Аренды владельца продлены.");
      setExtendOwnerHours("");
      setExtendOwnerMinutes("");
    } catch (error) {
      onToast((error as Error).message || "Не удалось продлить аренды владельца", true);
    }
  };

  const handleRelease = async () => {
    if (!account) {
      onToast("Сначала выберите аккаунт.", true);
      return;
    }
    try {
      await onRelease();
      onToast("Аккаунт освобождён.");
    } catch (error) {
      onToast((error as Error).message || "Не удалось освободить аккаунт", true);
    }
  };

  const handleExtend = async () => {
    if (!account) {
      onToast("Сначала выберите аккаунт.", true);
      return;
    }
    const hours = Number(extendHours || 0);
    const minutes = Number(extendMinutes || 0);
    if (extendHours === "" && extendMinutes === "") {
      onToast("Укажите часы или минуты для продления.", true);
      return;
    }
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
      onToast("Продление должно быть числом.", true);
      return;
    }
    if (hours < 0 || minutes < 0 || minutes > 59) {
      onToast("Минуты должны быть от 0 до 59.", true);
      return;
    }
    if (hours === 0 && minutes === 0) {
      onToast("Укажите часы или минуты для продления.", true);
      return;
    }
    try {
      await onExtend(hours, minutes);
      onToast("Аренда продлена.");
      setExtendHours("");
      setExtendMinutes("");
    } catch (error) {
      onToast((error as Error).message || "Не удалось продлить аренду", true);
    }
  };

  const handleDeauth = async () => {
    if (!account) {
      onToast("Сначала выберите аккаунт.", true);
      return;
    }
    try {
      onToast("Деавторизация Steam запущена...");
      await onDeauth();
      onToast("Сессии Steam деавторизованы.");
    } catch (error) {
      onToast((error as Error).message || "Не удалось деавторизовать Steam", true);
    }
  };

  const handleChangePassword = async () => {
    if (!account) {
      onToast("Сначала выберите аккаунт.", true);
      return;
    }
    try {
      onToast("Смена пароля Steam...");
      const newPassword = await onChangePassword(steamNewPassword.trim() || null);
      if (newPassword) {
        setPassword(newPassword);
        onToast(`Пароль Steam изменён: ${newPassword}`);
      } else {
        onToast("Пароль Steam изменён.");
      }
    } catch (error) {
      onToast((error as Error).message || "Не удалось изменить пароль Steam", true);
    }
  };

  const handleDelete = async () => {
    if (!account) {
      onToast("Сначала выберите аккаунт.", true);
      return;
    }
    if (!window.confirm("Удалить этот аккаунт?")) return;
    try {
      await onDelete();
      onToast("Аккаунт удалён.");
    } catch (error) {
      onToast((error as Error).message || "Не удалось удалить аккаунт", true);
    }
  };

  return (
    <div className="panel space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div>
          <label className="field-label">ID</label>
          <input className="input" value={account?.id ?? ""} disabled />
        </div>
        <div>
          <label className="field-label">Название аккаунта</label>
          <input className="input" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div>
          <label className="field-label">MMR</label>
          <input className="input" type="number" min={0} value={mmr} onChange={(event) => setMmr(event.target.value)} />
        </div>
        <div>
          <label className="field-label">Логин</label>
          <input className="input" value={login} onChange={(event) => setLogin(event.target.value)} />
        </div>
        <div>
          <label className="field-label">Пароль</label>
          <input className="input" value={password} onChange={(event) => setPassword(event.target.value)} />
        </div>
        <div>
          <label className="field-label">JSON maFile</label>
          <textarea className="textarea" rows={3} value={maFileJson} onChange={(event) => setMaFileJson(event.target.value)} />
        </div>
        <div>
          <label className="field-label">Длительность (часы)</label>
          <input
            className="input"
            type="number"
            min={0}
            value={durationHours}
            onChange={(event) => setDurationHours(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label">Длительность (минуты)</label>
          <input
            className="input"
            type="number"
            min={0}
            max={59}
            value={durationMinutes}
            onChange={(event) => setDurationMinutes(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label">Владелец</label>
          <input className="input" value={owner} onChange={(event) => setOwner(event.target.value)} />
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <button className="btn" type="button" onClick={handleUpdate}>
          Сохранить
        </button>
        <button className="btn" type="button" onClick={handleAssign}>
          Назначить владельца
        </button>
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 px-3 py-2">
          <input
            className="input w-24"
            type="number"
            min={0}
            placeholder="+часы"
            value={extendOwnerHours}
            onChange={(event) => setExtendOwnerHours(event.target.value)}
          />
          <input
            className="input w-24"
            type="number"
            min={0}
            max={59}
            placeholder="+минуты"
            value={extendOwnerMinutes}
            onChange={(event) => setExtendOwnerMinutes(event.target.value)}
          />
          <button className="btn-ghost" type="button" onClick={handleExtendOwner}>
            Продлить аренды
          </button>
        </div>
        <button className="btn-ghost" type="button" onClick={handleRelease}>
          Освободить
        </button>
        <button className="btn-ghost" type="button" onClick={handleDeauth}>
          Steam: деавторизовать
        </button>
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 px-3 py-2">
          <input
            className="input w-24"
            type="number"
            min={0}
            placeholder="+часы"
            value={extendHours}
            onChange={(event) => setExtendHours(event.target.value)}
          />
          <input
            className="input w-24"
            type="number"
            min={0}
            max={59}
            placeholder="+минуты"
            value={extendMinutes}
            onChange={(event) => setExtendMinutes(event.target.value)}
          />
          <button className="btn" type="button" onClick={handleExtend}>
            Продлить
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 px-3 py-2">
          <input
            className="input w-48"
            type="text"
            placeholder="Новый пароль Steam"
            value={steamNewPassword}
            onChange={(event) => setSteamNewPassword(event.target.value)}
          />
          <button className="btn-ghost" type="button" onClick={handleChangePassword}>
            Сменить пароль Steam
          </button>
        </div>
        <button className="btn-danger" type="button" onClick={handleDelete}>
          Удалить
        </button>
      </div>
    </div>
  );
};

export default ManageAccountPanel;
