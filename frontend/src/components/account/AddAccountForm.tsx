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

    const payload: Record<string, unknown> = {
      account_name: accountName.trim(),
      login: login.trim(),
      password: password.trim(),
      mafile_json: mafileJson.trim(),
      // defaults to satisfy backend without exposing in UI
      rental_duration: 1,
      rental_minutes: 0,
      mmr: 0,
    };

    try {
      await onSubmit(payload);
      onToast("Account created.");
      setAccountName("");
      setLogin("");
      setPassword("");
      setMafileJson("");
    } catch (error) {
      onToast((error as Error).message || "Failed to create account.", true);
    }
  };

  return (
    <form className="space-y-5" onSubmit={handleSubmit}>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Account name</label>
          <input
            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-3 text-sm text-neutral-900 shadow-sm outline-none focus:border-neutral-400"
            value={accountName}
            onChange={(event) => setAccountName(event.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Login</label>
          <input
            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-3 text-sm text-neutral-900 shadow-sm outline-none focus:border-neutral-400"
            value={login}
            onChange={(event) => setLogin(event.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Password</label>
          <input
            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-3 text-sm text-neutral-900 shadow-sm outline-none focus:border-neutral-400"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </div>
        <div className="space-y-2 md:col-span-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">maFile JSON</label>
          <textarea
            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-3 text-sm text-neutral-900 shadow-sm outline-none focus:border-neutral-400"
            rows={4}
            value={mafileJson}
            onChange={(event) => setMafileJson(event.target.value)}
            required
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          className="rounded-lg bg-neutral-900 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-neutral-800"
          type="submit"
        >
          Create account
        </button>
      </div>
    </form>
  );
};

export default AddAccountForm;
