import React, { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

type LoginPayload = { username: string; password: string };

type RegisterPayload = { username: string; password: string; golden_key: string };

type LoginPageProps = {
  onLogin: (payload: LoginPayload) => Promise<void>;
  onRegister: (payload: RegisterPayload) => Promise<void>;
  onToast: (message: string, isError?: boolean) => void;
};

type Lang = "en" | "ru";

type Mode = "login" | "register";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

const PAGE = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.55, ease: EASE } },
} as const;

const STAGGER = {
  animate: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } },
} as const;

const FADE_UP = {
  initial: { opacity: 0, y: 20, filter: "blur(10px)" },
  animate: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.6, ease: EASE, type: "spring", stiffness: 120, damping: 14, mass: 0.8 },
  },
  exit: {
    opacity: 0,
    y: -20,
    filter: "blur(10px)",
    transition: { duration: 0.35, ease: EASE },
  },
} as const;

const PANEL = {
  initial: { opacity: 0, scale: 0.98, y: 6, filter: "blur(10px)" },
  animate: { opacity: 1, scale: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.55, ease: EASE } },
  exit: { opacity: 0, scale: 0.98, y: -6, filter: "blur(10px)", transition: { duration: 0.35, ease: EASE } },
} as const;

const LEFT_PANEL = {
  initial: { opacity: 0, x: -60 },
  animate: { opacity: 1, x: 0, transition: { duration: 0.9, ease: EASE } },
} as const;

const RIGHT_PANEL = {
  initial: { opacity: 0, x: 60 },
  animate: { opacity: 1, x: 0, transition: { duration: 0.9, ease: EASE } },
} as const;

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

const LoginPage: React.FC<LoginPageProps> = ({ onLogin, onRegister, onToast }) => {
  const [lang, setLang] = useState<Lang>(() => {
    if (typeof window === "undefined") return "en";
    const stored = window.localStorage.getItem("lang");
    if (stored === "ru" || stored === "en") return stored;
    return window.navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en";
  });

  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [goldenKey, setGoldenKey] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showForgot, setShowForgot] = useState(false);
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
      titleLogin: "Вход",
      subtitleLogin: "Войдите, чтобы открыть панель управления.",
      titleRegister: "Регистрация",
      subtitleRegister: "Создайте аккаунт и подключите золотой ключ FunPay.",
      usernamePlaceholder: "Email или логин",
      passwordPlaceholder: "Пароль",
      goldenKeyPlaceholder: "Золотой ключ FunPay",
      forgotPassword: "Забыли пароль?",
      forgotPasswordHint: "Восстановление пароля пока не подключено.",
      actionLogin: "Войти",
      actionRegister: "Создать аккаунт",
      working: "Подождите...",
      marketingTitle: "Автоматизируйте свой процесс",
      marketingSubtitle:
        "Аккаунты, аренды, лоты, уведомления и чаты — в одной панели. Быстрее, чище, без рутины.",
      bullet1: "Выдача аккаунтов и продление аренды в пару кликов",
      bullet2: "Чаты FunPay и уведомления в реальном времени",
      bullet3: "Инвентарь, лоты и статистика — всё под контролем",
      footerLeft: `© ${year} FunpayMegamind`,
      footerSupport: "Поддержка",
      supportHint: "Поддержка скоро.",
      validation: "Введите логин и пароль.",
      validationRegister: "Заполните логин, пароль и золотой ключ.",
      linkSignUp: "Регистрация",
      linkSignIn: "Войти",
      badge: "Автоматизация для продавцов FunPay",
    } as const;

    const EN = {
      titleLogin: "Sign In",
      subtitleLogin: "Sign in to access your dashboard.",
      titleRegister: "Sign Up",
      subtitleRegister: "Create an account and connect your FunPay golden key.",
      usernamePlaceholder: "Email or Username",
      passwordPlaceholder: "Password",
      goldenKeyPlaceholder: "FunPay Golden Key",
      forgotPassword: "Forgot password?",
      forgotPasswordHint: "Password reset isn't wired up yet.",
      actionLogin: "Sign In",
      actionRegister: "Create account",
      working: "Working...",
      marketingTitle: "Automate your workflow",
      marketingSubtitle:
        "Accounts, rentals, lots, notifications, and chats — in one dashboard. Faster, cleaner, less routine.",
      bullet1: "Issue accounts and extend rentals in a couple clicks",
      bullet2: "FunPay chats and realtime notifications",
      bullet3: "Inventory, lots, and stats — always in control",
      footerLeft: `© ${year} FunpayMegamind`,
      footerSupport: "Support",
      supportHint: "Support coming soon.",
      validation: "Enter username and password.",
      validationRegister: "Enter username, password, and golden key.",
      linkSignUp: "Sign Up",
      linkSignIn: "Sign In",
      badge: "Automation for FunPay sellers",
    } as const;

    return lang === "ru" ? RU : EN;
  }, [lang]);

  const canSubmit = useMemo(() => {
    if (submitting) return false;
    if (mode === "login") return username.trim().length > 0 && password.trim().length > 0;
    return (
      username.trim().length > 0 && password.trim().length > 0 && goldenKey.trim().length > 0
    );
  }, [mode, username, password, goldenKey, submitting]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (mode === "login") {
      if (!username.trim() || !password.trim()) {
        onToast(copy.validation, true);
        setShowForgot(true);
        return;
      }
      try {
        setSubmitting(true);
        await onLogin({ username: username.trim(), password: password.trim() });
        setShowForgot(false);
      } catch (err) {
        setShowForgot(true);
        throw err;
      } finally {
        setSubmitting(false);
      }
      return;
    }

    if (!username.trim() || !password.trim() || !goldenKey.trim()) {
      onToast(copy.validationRegister, true);
      return;
    }

    try {
      setSubmitting(true);
      await onRegister({
        username: username.trim(),
        password: password.trim(),
        golden_key: goldenKey.trim(),
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <motion.div className="min-h-screen bg-white" variants={PAGE} initial="initial" animate="animate">
      <div className="grid min-h-screen grid-cols-1 md:grid-cols-2">
        <motion.aside
          className="relative flex flex-col overflow-hidden bg-gradient-to-br from-neutral-950 via-neutral-900 to-neutral-800 p-10 text-white md:p-14"
          variants={LEFT_PANEL}
          initial="initial"
          animate="animate"
        >
          <div className="pointer-events-none absolute inset-0 opacity-40 [background:radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.08),transparent_55%),radial-gradient(circle_at_70%_80%,rgba(255,122,24,0.14),transparent_55%)]" />
          <motion.div
            className="pointer-events-none absolute -left-24 -top-24 h-80 w-80 rounded-full bg-gradient-to-br from-orange-400/35 via-red-500/15 to-pink-500/25 blur-3xl"
            animate={{
              scale: [1, 1.15, 1],
              x: [0, 30, 0],
              y: [0, -20, 0],
              transition: { duration: 18, ease: "easeInOut", repeat: Infinity, repeatType: "mirror" },
            }}
          />
          <motion.div
            className="pointer-events-none absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-gradient-to-br from-white/10 via-white/10 to-white/0 blur-3xl"
            animate={{
              scale: [1, 1.2, 1],
              x: [0, -30, 0],
              y: [0, 20, 0],
              transition: { duration: 15, ease: "easeInOut", repeat: Infinity, repeatType: "mirror" },
            }}
          />

          <div className="h-16" />

          <div className="relative z-10 flex flex-1 items-center justify-center">
            <motion.div className="w-full max-w-lg text-center" variants={STAGGER} initial="initial" animate="animate">
              <motion.p
                className="mx-auto inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs font-medium text-white/70 backdrop-blur"
                variants={FADE_UP}
              >
                {copy.badge}
              </motion.p>

              <AnimatePresence mode="wait">
                <motion.h2
                  key={`hero-title-${lang}`}
                  className="mt-10 text-4xl font-semibold leading-tight tracking-tight md:text-[52px]"
                  variants={FADE_UP}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  {copy.marketingTitle}
                </motion.h2>
              </AnimatePresence>
              <AnimatePresence mode="wait">
                <motion.p
                  key={`hero-sub-${lang}`}
                  className="mx-auto mt-5 max-w-[56ch] text-sm leading-relaxed text-white/70"
                  variants={FADE_UP}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  {copy.marketingSubtitle}
                </motion.p>
              </AnimatePresence>

              <motion.div className="mx-auto mt-9 max-w-md space-y-3 text-left text-sm text-white/80" variants={STAGGER}>
                <motion.div className="flex items-start gap-3" variants={FADE_UP}>
                  <span className="mt-0.5 text-orange-300">
                    <CheckIcon />
                  </span>
                  <span>{copy.bullet1}</span>
                </motion.div>
                <motion.div className="flex items-start gap-3" variants={FADE_UP}>
                  <span className="mt-0.5 text-orange-300">
                    <CheckIcon />
                  </span>
                  <span>{copy.bullet2}</span>
                </motion.div>
                <motion.div className="flex items-start gap-3" variants={FADE_UP}>
                  <span className="mt-0.5 text-orange-300">
                    <CheckIcon />
                  </span>
                  <span>{copy.bullet3}</span>
                </motion.div>
              </motion.div>

              <motion.div className="relative mx-auto mt-12 w-full max-w-sm" variants={FADE_UP}>
                <div className="pointer-events-none absolute -left-10 -top-10 h-24 w-24 rounded-[28px] bg-gradient-to-br from-orange-500/25 to-pink-500/10 blur-lg" />
                <div className="pointer-events-none absolute -bottom-12 -right-10 h-32 w-32 rounded-full bg-gradient-to-br from-white/10 to-white/0 blur-2xl" />

                <motion.div
                  className="relative w-full rounded-[34px] border border-white/10 bg-white/5 p-6 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur"
                  whileHover={{ y: -4, transition: { duration: 0.25, ease: EASE } }}
                >
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
                </motion.div>
              </motion.div>
            </motion.div>
          </div>

          <div className="h-16" />
        </motion.aside>

        <main className="relative flex flex-col bg-white p-10 md:p-14">
          <div className="flex h-16 items-center justify-end">
            <motion.button
              type="button"
              className="text-sm font-semibold text-neutral-600 transition hover:text-neutral-900"
              onClick={() => setMode((prev) => (prev === "login" ? "register" : "login"))}
              variants={FADE_UP}
              initial="initial"
              animate="animate"
            >
              {mode === "login" ? copy.linkSignUp : copy.linkSignIn}
            </motion.button>
          </div>

          <div className="flex flex-1 items-center justify-center">
            <AnimatePresence mode="wait">
              <motion.div key={mode} className="w-full max-w-md" {...PANEL}>
                <motion.h1 className="text-[44px] font-semibold leading-none tracking-tight text-neutral-900" {...FADE_UP}>
                  {mode === "login" ? copy.titleLogin : copy.titleRegister}
                </motion.h1>
                <motion.p className="mt-3 text-sm text-neutral-500" {...FADE_UP}>
                  {mode === "login" ? copy.subtitleLogin : copy.subtitleRegister}
                </motion.p>

                <motion.form className="mt-10 space-y-5" onSubmit={handleSubmit} variants={STAGGER} initial="initial" animate="animate">
                  <motion.div variants={FADE_UP}>
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
                  </motion.div>

                  <motion.div className="relative" variants={FADE_UP}>
                    <label className="sr-only" htmlFor="login-password">
                      {copy.passwordPlaceholder}
                    </label>
                    <input
                      id="login-password"
                      className="w-full rounded-full border border-neutral-200 bg-white px-6 py-4 pr-14 text-[15px] text-neutral-900 placeholder:text-neutral-400 shadow-sm shadow-black/5 outline-none transition focus:border-neutral-300 focus:ring-4 focus:ring-orange-500/10"
                      placeholder={copy.passwordPlaceholder}
                      type={showPassword ? "text" : "password"}
                      autoComplete={mode === "login" ? "current-password" : "new-password"}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                    <motion.button
                      type="button"
                      className="absolute inset-y-0 right-3 inline-flex h-full w-11 items-center justify-center rounded-full p-0 text-neutral-400 transition hover:text-neutral-600 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-neutral-300 focus-visible:outline-offset-2"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      onClick={() => setShowPassword((prev) => !prev)}
                      animate={{ rotate: showPassword ? 45 : 0, opacity: 1, scale: 1 }}
                      transition={{ duration: 0.2, ease: EASE }}
                    >
                      <EyeIcon hidden={showPassword} />
                    </motion.button>
                  </motion.div>

                  <AnimatePresence mode="popLayout" initial={false}>
                    {mode === "register" ? (
                      <motion.div key="golden" variants={FADE_UP} {...PANEL}>
                        <label className="sr-only" htmlFor="login-golden">
                          {copy.goldenKeyPlaceholder}
                        </label>
                        <input
                          id="login-golden"
                          className="w-full rounded-full border border-neutral-200 bg-white px-6 py-4 text-[15px] text-neutral-900 placeholder:text-neutral-400 shadow-sm shadow-black/5 outline-none transition focus:border-neutral-300 focus:ring-4 focus:ring-orange-500/10"
                          placeholder={copy.goldenKeyPlaceholder}
                          value={goldenKey}
                          onChange={(event) => setGoldenKey(event.target.value)}
                        />
                      </motion.div>
                    ) : showForgot ? (
                      <motion.button
                        key="forgot"
                        type="button"
                        className="text-left text-sm font-medium text-orange-500 transition hover:text-orange-600"
                        onClick={() => onToast(copy.forgotPasswordHint, true)}
                        variants={FADE_UP}
                        initial="initial"
                        animate="animate"
                        exit="exit"
                        whileHover={{ x: 5 }}
                        transition={{ type: "spring", stiffness: 300, damping: 20 }}
                      >
                        {copy.forgotPassword}
                      </motion.button>
                    ) : (
                      <motion.div
                        key="signup"
                        className="text-sm text-neutral-500"
                        variants={FADE_UP}
                        initial="initial"
                        animate="animate"
                        exit="exit"
                      >
                        <span className="mr-2">{lang === "ru" ? "Нет аккаунта?" : "Don't have an account?"}</span>
                        <button
                          type="button"
                          className="font-semibold text-orange-500 transition hover:text-orange-600"
                          onClick={() => setMode("register")}
                        >
                          {copy.linkSignUp}
                        </button>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  <motion.button
                    type="submit"
                    disabled={!canSubmit}
                    className="group mt-2 flex w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-orange-500 via-red-500 to-pink-500 py-4 text-sm font-semibold text-white shadow-lg shadow-orange-500/25 transition hover:brightness-105 focus:outline-none focus:ring-4 focus:ring-orange-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                    variants={FADE_UP}
                    whileHover={{ y: -2 }}
                    whileTap={{ scale: 0.98 }}
                  >
                    <span className="inline-flex items-center gap-2">
                      <span className="grid h-9 w-9 place-items-center rounded-full bg-white/15">
                        <ArrowIcon />
                      </span>
                      {submitting
                        ? copy.working
                        : mode === "login"
                          ? copy.actionLogin
                          : copy.actionRegister}
                    </span>
                  </motion.button>
                </motion.form>
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="flex h-16 flex-wrap items-center justify-between gap-3 text-xs text-neutral-400">
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
                Русский
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
    </motion.div>
  );
};

export default LoginPage;
