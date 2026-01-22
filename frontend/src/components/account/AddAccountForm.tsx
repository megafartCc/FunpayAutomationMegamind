import React, { useState } from "react";

type AddAccountFormProps = {
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

const AddAccountForm: React.FC<AddAccountFormProps> = ({ onSubmit, onToast }) => {
  const [accountName, setAccountName] = useState("");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [mafileJson, setMafileJson] = useState("");
  const [mmr, setMmr] = useState("");
  const [durationHours, setDurationHours] = useState("1");
  const [durationMinutes, setDurationMinutes] = useState("0");
  const [owner, setOwner] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!accountName.trim() || !login.trim() || !password.trim()) {
      onToast("Account name, login, and password are required.", true);
      return;
    }
    if (!mafileJson.trim()) {
      onToast("maFile JSON is required.", true);
      return;
    }

    const hours = Number(durationHours || 0);
    const minutes = Number(durationMinutes || 0);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
      onToast("Duration must be a number.", true);
      return;
    }
    if (hours < 0 || minutes < 0 || minutes > 59) {
      onToast("Minutes must be between 0 and 59.", true);
      return;
    }
    if (hours === 0 && minutes === 0) {
      onToast("Duration must be greater than 0.", true);
      return;
    }

    const mmrValue = mmr.trim() === "" ? 0 : Number(mmr);
    if (!Number.isFinite(mmrValue) || mmrValue < 0) {
      onToast("MMR must be a number 0 or higher.", true);
      return;
    }

    const payload: Record<string, unknown> = {
      account_name: accountName.trim(),
      login: login.trim(),
      password: password.trim(),
      mafile_json: mafileJson.trim(),
      mmr: Math.floor(mmrValue),
      rental_duration: Math.floor(hours),
      rental_minutes: Math.floor(minutes),
    };
    if (owner.trim()) {
      payload.owner = owner.trim();
    }

    try {
      await onSubmit(payload);
      onToast("Account created.");
      setAccountName("");
      setLogin("");
      setPassword("");
      setMafileJson("");
      setMmr("");
      setDurationHours("1");
      setDurationMinutes("0");
      setOwner("");
    } catch (error) {
      onToast((error as Error).message || "Failed to create account.", true);
    }
  };

  return (
    <form className="panel space-y-4" onSubmit={handleSubmit}>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div>
          <label className="field-label">Account name</label>
          <input
            className="input"
            value={accountName}
            onChange={(event) => setAccountName(event.target.value)}
            required
          />
        </div>
        <div>
          <label className="field-label">Login</label>
          <input className="input" value={login} onChange={(event) => setLogin(event.target.value)} required />
        </div>
        <div>
          <label className="field-label">Password</label>
          <input className="input" value={password} onChange={(event) => setPassword(event.target.value)} required />
        </div>
        <div>
          <label className="field-label">MMR</label>
          <input
            className="input"
            type="number"
            min={0}
            value={mmr}
            onChange={(event) => setMmr(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label">Duration (hours)</label>
          <input
            className="input"
            type="number"
            min={0}
            value={durationHours}
            onChange={(event) => setDurationHours(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label">Duration (minutes)</label>
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
          <label className="field-label">Owner (optional)</label>
          <input className="input" value={owner} onChange={(event) => setOwner(event.target.value)} />
        </div>
        <div className="md:col-span-2 xl:col-span-3">
          <label className="field-label">maFile JSON</label>
          <textarea
            className="textarea"
            rows={4}
            value={mafileJson}
            onChange={(event) => setMafileJson(event.target.value)}
            required
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <button className="btn" type="submit">
          Create account
        </button>
      </div>
    </form>
  );
};

export default AddAccountForm;
