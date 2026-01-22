import React, { useState } from "react";

type AuthOverlayProps = {
  visible: boolean;
  onRegister: (payload: { username: string; password: string; golden_key: string }) => Promise<void>;
  onLogin: (payload: { username: string; password: string }) => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

const AuthOverlay: React.FC<AuthOverlayProps> = ({ visible, onRegister, onLogin, onToast }) => {
  const [regUsername, setRegUsername] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regGoldenKey, setRegGoldenKey] = useState("");
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  if (!visible) return null;

  const handleRegister = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!regUsername || !regPassword || !regGoldenKey) {
      onToast("Заполните все поля.", true);
      return;
    }
    await onRegister({ username: regUsername.trim(), password: regPassword.trim(), golden_key: regGoldenKey.trim() });
  };

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!loginUsername || !loginPassword) {
      onToast("Заполните все поля.", true);
      return;
    }
    await onLogin({ username: loginUsername.trim(), password: loginPassword.trim() });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6">
      <div className="w-full max-w-4xl rounded-3xl border border-slate-800 bg-panel/90 p-8">
        <h2 className="text-xl font-semibold">Доступ</h2>
        <p className="text-sm text-slate-400">Зарегистрируйтесь с золотым ключом и войдите в панель.</p>
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <form className="space-y-4" onSubmit={handleRegister}>
            <h3 className="text-lg font-semibold">Регистрация</h3>
            <div>
              <label className="field-label">Логин</label>
              <input className="input" value={regUsername} onChange={(event) => setRegUsername(event.target.value)} required />
            </div>
            <div>
              <label className="field-label">Пароль</label>
              <input className="input" type="password" value={regPassword} onChange={(event) => setRegPassword(event.target.value)} required />
            </div>
            <div>
              <label className="field-label">Золотой ключ FunPay</label>
              <input className="input" value={regGoldenKey} onChange={(event) => setRegGoldenKey(event.target.value)} required />
            </div>
            <button className="btn w-full" type="submit">Зарегистрироваться</button>
          </form>
          <form className="space-y-4" onSubmit={handleLogin}>
            <h3 className="text-lg font-semibold">Вход</h3>
            <div>
              <label className="field-label">Логин</label>
              <input className="input" value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} required />
            </div>
            <div>
              <label className="field-label">Пароль</label>
              <input className="input" type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} required />
            </div>
            <button className="btn w-full" type="submit">Войти</button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default AuthOverlay;
