import React, { useEffect, useMemo, useState } from "react";

type LoginPageProps = {
  onLogin: (payload: { username: string; password: string }) => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

type Lang = "en" | "ru";

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

const CheckIcon: React.FC = () => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    className="h-5 w-5"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M20 6L9 17l-5-5" />
  </svg>
);

const LoginPage: React.FC<LoginPageProps> = ({ onLogin, onToast }) => {
  const [lang, setLang] = useState<Lang>(() => {
    if (typeof window === "undefined") return "en";
    const stored = window.localStorage.getItem("lang");
    if (stored === "ru" || stored === "en") return stored;
    return window.navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en";
  });

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    try {
      window.localStorage.setItem("lang", lang);
    } catch {
      // ignore
    }
  }, [lang]);

  const copy = useMemo(() => {
    const year = new Date().getFullYear();

    const RU = {
      brand: "FunpayMegamind",
      signUp: "???????????",
      signUpHint: "????? ??????? ???????????.",
      title: "????",
      subtitle: "???????, ????? ??????? ?????? ??????????.",
      usernamePlaceholder: "Email ??? ?????",
      passwordPlaceholder: "??????",
      forgotPassword: "?????? ???????",
      forgotPasswordHint: "?????????????? ?????? ???? ?? ??????????.",
      signIn: "?????",
      signingIn: "??????...",
      marketingTag: "????????????? ??? ????????? FunPay",
      marketingTitle: "??????????????? ???? ???????",
      marketingSubtitle:
        "????????, ??????, ????, ??????????? ? ???? ? ? ????? ??????. ???????, ????, ??? ??????.",
      bullet1: "?????? ????????? ? ????????? ?????? ? ???? ??????",
      bullet2: "???? FunPay ? ??????????? ? ???????? ???????",
      bullet3: "?????????, ???? ? ?????????? ? ??? ??? ?????????",
      footerLeft: `? ${year} FunpayMegamind`,
      footerSupport: "?????????",
      supportHint: "????????? ?????.",
      validation: "??????? ????? ? ??????.",
    } as const;

    const EN = {
      brand: "FunpayMegamind",
      signUp: "Sign Up",
      signUpHint: "Sign up is coming soon.",
      title: "Sign In",
      subtitle: "Sign in to access your dashboard.",
      usernamePlaceholder: "Email or Username",
      passwordPlaceholder: "Password",
      forgotPassword: "Forgot password?",
      forgotPasswordHint: "Password reset isn't wired up yet.",
      signIn: "Sign In",
      signingIn: "Signing In...",
      marketingTag: "Automation for FunPay sellers",
      marketingTitle: "Automate your workflow",
      marketingSubtitle:
        "Accounts, rentals, lots, notifications, and chats ? in one dashboard. Faster, cleaner, less routine.",
      bullet1: "Issue accounts and extend rentals in a couple clicks",
      bullet2: "FunPay chats and realtime notifications",
      bullet3: "Inventory, lots, and stats ? always in control",
      footerLeft: `? ${year} FunpayMegamind`,
      footerSupport: "Support",
      supportHint: "Support coming soon.",
      validation: "Enter username and password.",
    } as const;

    return lang === "ru" ? RU : EN;
  }, [lang]);

  const canSubmit = useMemo(
    () => username.trim().length > 0 && password.trim().length > 0 && !submitting,
    [username, password, submitting]
  );

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password.trim()) {
      onToast(copy.validation, true);
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
    <div className="min-h-screen bg-[#f3f4f6] px-6 py-10">
      <div className="mx-auto w-full max-w-6xl">
        <div className="relative overflow-hidden rounded-[44px] border border-neutral-200/70 bg-white shadow-[0_40px_140px_rgba(0,0,0,0.18)]">
          <div className="pointer-events-none absolute -left-24 -top-24 h-80 w-80 rounded-full bg-gradient-to-br from-orange-400/30 via-red-500/10 to-pink-500/25 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-gradient-to-br from-slate-900/10 via-slate-900/10 to-slate-900/0 blur-3xl" />

          <div className="grid min-h-[680px] grid-cols-1 md:grid-cols-2">
            <aside className="relative overflow-hidden bg-gradient-to-br from-neutral-950 via-neutral-900 to-neutral-800 p-10 text-white md:p-12">
              <div className="pointer-events-none absolute inset-0 opacity-40 [background:radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.08),transparent_55%),radial-gradient(circle_at_70%_80%,rgba(255,122,24,0.14),transparent_55%)]" />

              <div className="relative z-10 flex h-full flex-col">
                <div className="inline-flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-white/10 ring-1 ring-white/10">
                    <span className="h-3 w-3 rounded-full bg-gradient-to-br from-orange-400 to-pink-500" />
                  </span>
                  <div className="leading-tight">
                    <div className="text-sm font-semibold tracking-wide">{copy.brand}</div>
                    <div className="text-xs text-white/60">{copy.marketingTag}</div>
                  </div>
                </div>

                <div className="mt-10">
                  <h2 className="text-4xl font-semibold leading-tight tracking-tight md:text-[44px]">{copy.marketingTitle}</h2>
                  <p className="mt-4 max-w-[46ch] text-sm leading-relaxed text-white/70">{copy.marketingSubtitle}</p>

                  <div className="mt-8 space-y-3 text-sm text-white/80">
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 text-orange-300">
                        <CheckIcon />
                      </span>
                      <span>{copy.bullet1}</span>
                    </div>
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 text-orange-300">
                        <CheckIcon />
                      </span>
                      <span>{copy.bullet2}</span>
                    </div>
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 text-orange-300">
                        <CheckIcon />
                      </span>
                      <span>{copy.bullet3}</span>
                    </div>
                  </div>
                </div>

                <div className="mt-10 grow" />

                <div className="relative z-10 mt-10">
                  <div className="absolute -left-10 -top-10 h-24 w-24 rounded-[28px] bg-gradient-to-br from-orange-500/25 to-pink-500/10 blur-lg" />
                  <div className="absolute -bottom-12 -right-10 h-32 w-32 rounded-full bg-gradient-to-br from-white/10 to-white/0 blur-2xl" />

                  <div className="relative mx-auto w-full max-w-sm rounded-[34px] border border-white/10 bg-white/5 p-6 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur">
                    <div className="flex items-center justify-between">
                      <div className="h-3 w-28 rounded-full bg-white/15" />
                      <div className="h-9 w-9 rounded-2xl bg-gradient-to-br from-orange-400/90 to-pink-500/70" />
                    </div>
                    <div className="mt-6 space-y-3">
                      <div className="h-12 rounded-2xl bg-white/10" />
                      <div className="grid grid-cols-3 gap-3">
                        <div className="h-16 rounded-2xl bg-white/10" />
                        <div className="h-16 rounded-2xl bg-white/10" />
                        <div className="h-16 rounded-2xl bg-white/10" />
                      </div>
                      <div className="h-10 rounded-2xl bg-gradient-to-r from-orange-500/35 via-red-500/25 to-pink-500/30" />
                    </div>
                  </div>
                </div>
              </div>
            </aside>

            <main className="relative flex flex-col p-10 md:p-12 lg:p-14">
              <div className="flex items-center justify-between">
                <div className="inline-flex items-center gap-2 text-neutral-900">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-neutral-900 text-white">
                    <span className="h-3 w-3 rounded-full bg-gradient-to-br from-orange-400 to-pink-500" />
                  </span>
                  <span className="text-sm font-semibold tracking-wide">{copy.brand}</span>
                </div>

                <button
                  type="button"
                  className="text-sm font-semibold text-neutral-600 transition hover:text-neutral-900"
                  onClick={() => onToast(copy.signUpHint, true)}
                >
                  {copy.signUp}
                </button>
              </div>

              <div className="mt-12">
                <h1 className="text-[42px] font-semibold leading-none tracking-tight text-neutral-900">{copy.title}</h1>
                <p className="mt-3 text-sm text-neutral-500">{copy.subtitle}</p>
              </div>

              <form className="mt-10 space-y-5" onSubmit={handleSubmit}>
                <div>
                  <label className="sr-only" htmlFor="login-username">
                    {copy.usernamePlaceholder}
                  </label>
                  <input
                    id="login-username"
                    className="w-full rounded-full border border-neutral-200 bg-white px-6 py-4 text-[15px] text-neutral-900 placeholder:text-neutral-400 shadow-sm shadow-black/5 outline-none transition focus:border-neutral-300 focus:ring-4 focus:ring-orange-500/10"
                    placeholder={copy.usernamePlaceholder}
                    autoComplete="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                  />
                </div>

                <div className="relative">
                  <label className="sr-only" htmlFor="login-password">
                    {copy.passwordPlaceholder}
                  </label>
                  <input
                    id="login-password"
                    className="w-full rounded-full border border-neutral-200 bg-white px-6 py-4 pr-14 text-[15px] text-neutral-900 placeholder:text-neutral-400 shadow-sm shadow-black/5 outline-none transition focus:border-neutral-300 focus:ring-4 focus:ring-orange-500/10"
                    placeholder={copy.passwordPlaceholder}
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  <button
                    type="button"
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-3 text-neutral-400 transition hover:text-neutral-600 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-neutral-300 focus-visible:outline-offset-2"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    onClick={() => setShowPassword((prev) => !prev)}
                  >
                    <EyeIcon hidden={showPassword} />
                  </button>
                </div>

                <button
                  type="button"
                  className="text-sm font-medium text-orange-500 transition hover:text-orange-600"
                  onClick={() => onToast(copy.forgotPasswordHint, true)}
                >
                  {copy.forgotPassword}
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
                    {submitting ? copy.signingIn : copy.signIn}
                  </span>
                </button>
              </form>

              <div className="mt-10 grow" />

              <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-neutral-400">
                <div className="flex items-center gap-4">
                  <span>{copy.footerLeft}</span>
                  <button
                    type="button"
                    className="font-medium text-neutral-500 transition hover:text-neutral-700"
                    onClick={() => onToast(copy.supportHint, true)}
                  >
                    {copy.footerSupport}
                  </button>
                </div>

                <div className="inline-flex items-center rounded-full border border-neutral-200 bg-white p-1 shadow-sm shadow-black/5">
                  <button
                    type="button"
                    className={
                      "rounded-full px-3 py-1.5 text-xs font-semibold transition " +
                      (lang === "ru" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:text-neutral-900")
                    }
                    onClick={() => setLang("ru")}
                  >
                    ???????
                  </button>
                  <button
                    type="button"
                    className={
                      "rounded-full px-3 py-1.5 text-xs font-semibold transition " +
                      (lang === "en" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:text-neutral-900")
                    }
                    onClick={() => setLang("en")}
                  >
                    English
                  </button>
                </div>
              </div>
            </main>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
