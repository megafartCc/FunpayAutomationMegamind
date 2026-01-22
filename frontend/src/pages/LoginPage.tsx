import React, { useMemo, useState } from "react";

type LoginPageProps = {
  onLogin: (payload: { username: string; password: string }) => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

const EyeIcon: React.FC<{ hidden?: boolean }> = ({ hidden }) => {
  // Minimal inline icon to avoid pulling an icon dependency.
  if (hidden) {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-5 w-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M3 3l18 18" />
        <path d="M10.6 10.6A2 2 0 0012 14a2 2 0 01-1.4-3.4z" />
        <path d="M9.9 5.1A10.5 10.5 0 0112 5c7 0 10 7 10 7a17.7 17.7 0 01-4 5.2" />
        <path d="M6.4 6.4A17.7 17.7 0 002 12s3 7 10 7a10.5 10.5 0 005.3-1.4" />
      </svg>
    );
  }

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
};

const ArrowIcon: React.FC = () => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    className="h-5 w-5"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M10 17l5-5-5-5" />
    <path d="M4 12h11" />
  </svg>
);

const LoginPage: React.FC<LoginPageProps> = ({ onLogin, onToast }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = useMemo(
    () => username.trim().length > 0 && password.trim().length > 0 && !submitting,
    [username, password, submitting]
  );

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password.trim()) {
      onToast("Enter username and password.", true);
      return;
    }
    try {
      setSubmitting(true);
      await onLogin({ username: username.trim(), password: password.trim() });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-6 py-10">
      <div className="w-full max-w-[460px] rounded-[32px] border border-neutral-200/80 bg-white p-10 shadow-[0_24px_70px_rgba(0,0,0,0.08)]">
        <h1 className="text-[44px] font-semibold leading-none tracking-tight text-neutral-900">
          Sign In
        </h1>

        <form className="mt-10 space-y-5" onSubmit={handleSubmit}>
          <div>
            <label className="sr-only" htmlFor="login-username">
              Email or Username
            </label>
            <input
              id="login-username"
              className="w-full rounded-full border border-neutral-200 bg-white px-6 py-4 text-[15px] text-neutral-900 placeholder:text-neutral-400 shadow-sm shadow-black/5 outline-none transition focus:border-neutral-300 focus:ring-4 focus:ring-orange-500/10"
              placeholder="Email or Username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>

          <div className="relative">
            <label className="sr-only" htmlFor="login-password">
              Password
            </label>
            <input
              id="login-password"
              className="w-full rounded-full border border-neutral-200 bg-white px-6 py-4 pr-14 text-[15px] text-neutral-900 placeholder:text-neutral-400 shadow-sm shadow-black/5 outline-none transition focus:border-neutral-300 focus:ring-4 focus:ring-orange-500/10"
              placeholder="Password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button
              type="button"
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-3 text-neutral-400 transition hover:text-neutral-600 focus:outline-none focus:ring-4 focus:ring-orange-500/10"
              aria-label={showPassword ? "Hide password" : "Show password"}
              onClick={() => setShowPassword((prev) => !prev)}
            >
              <EyeIcon hidden={showPassword} />
            </button>
          </div>

          <button
            type="button"
            className="text-sm font-medium text-orange-500 transition hover:text-orange-600"
            onClick={() => onToast("Password reset isn’t wired up yet.", true)}
          >
            Forgot password?
          </button>

          <button
            type="submit"
            disabled={!canSubmit}
            className="group mt-2 flex w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-orange-500 via-red-500 to-pink-500 py-4 text-sm font-semibold text-white shadow-lg shadow-orange-500/25 transition hover:brightness-105 focus:outline-none focus:ring-4 focus:ring-orange-500/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="inline-flex items-center gap-2">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-white/15">
                <ArrowIcon />
              </span>
              {submitting ? "Signing In..." : "Sign In"}
            </span>
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;
