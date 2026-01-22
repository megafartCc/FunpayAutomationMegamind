import React, { useState } from "react";

type SettingsPanelProps = {
  onUpdateGoldenKey: (key: string) => Promise<void>;
  onLogout: () => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

const SettingsPanel: React.FC<SettingsPanelProps> = ({ onUpdateGoldenKey, onLogout, onToast }) => {
  const [goldenKey, setGoldenKey] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!goldenKey.trim()) {
      onToast("Введите золотой ключ.", true);
      return;
    }
    try {
      await onUpdateGoldenKey(goldenKey.trim());
      onToast("Золотой ключ обновлён.");
    } catch (error) {
      onToast((error as Error).message || "Не удалось обновить ключ", true);
    }
  };

  const handleLogout = async () => {
    try {
      await onLogout();
    } finally {
      onToast("Вы вышли из аккаунта.");
    }
  };

  return (
    <div className="panel">
      <form className="grid gap-4 md:grid-cols-[1fr_auto]" onSubmit={handleSubmit}>
        <div>
          <label className="field-label">Новый золотой ключ FunPay</label>
          <input
            className="input"
            value={goldenKey}
            onChange={(event) => setGoldenKey(event.target.value)}
            placeholder="Введите ключ"
            required
          />
        </div>
        <div className="flex items-end gap-2">
          <button className="btn" type="submit">
            Сохранить
          </button>
          <button className="btn-ghost" type="button" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </form>
    </div>
  );
};

export default SettingsPanel;
