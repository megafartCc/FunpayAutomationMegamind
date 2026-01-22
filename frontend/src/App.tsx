import React, { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Toast from "./components/common/Toast";
import LoginPage from "./pages/LoginPage";
import { createApiClient } from "./services/api";
import { useToast } from "./hooks/useToast";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

const NAV_ITEMS = [
  { id: "overview", label: "Обзор", icon: "🏠" },
  { id: "rentals", label: "Активные аренды", icon: "🧾" },
  { id: "inventory", label: "Инвентарь", icon: "📦" },
  { id: "lots", label: "Лоты", icon: "🎟️" },
  { id: "chats", label: "Чаты", icon: "💬" },
  { id: "manage", label: "Управление аккаунтом", icon: "👤" },
  { id: "add", label: "Добавить аккаунт", icon: "➕" },
  { id: "notifications", label: "Уведомления", icon: "🔔" },
  { id: "settings", label: "Настройки", icon: "⚙️" },
];

const App: React.FC = () => {
  const [token, setToken] = useState(() => sessionStorage.getItem("adminToken") || "");
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const { toast, showToast } = useToast();

  const api = useMemo(
    () =>
      createApiClient({
        getToken: () => token,
        onUnauthorized: () => {
          sessionStorage.removeItem("adminToken");
          sessionStorage.removeItem("adminUser");
          setToken("");
        },
      }),
    [token]
  );

  const apiFetch = api.apiFetch;

  useEffect(() => {
    const desired = token
      ? "/"
      : pathname === "/login" || pathname === "/authentication" || pathname === "/authencation"
        ? pathname
        : "/authencation";
    if (pathname !== desired) {
      window.history.replaceState(null, "", desired);
      setPathname(desired);
    }
  }, [token, pathname]);

  const handleRegister = async (payload: { username: string; password: string; golden_key: string }) => {
    try {
      const data = await apiFetch<{ token: string; username: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      sessionStorage.setItem("adminToken", data.token);
      sessionStorage.setItem("adminUser", data.username);
      setToken(data.token);
      showToast("Регистрация выполнена, вы вошли.");
    } catch (error) {
      showToast((error as Error).message || "Не удалось зарегистрироваться", "error");
    }
  };

  const handleLogin = async (payload: { username: string; password: string }) => {
    try {
      const data = await apiFetch<{ token: string; username: string }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      sessionStorage.setItem("adminToken", data.token);
      sessionStorage.setItem("adminUser", data.username);
      setToken(data.token);
      showToast("Вход выполнен.");
    } catch (error) {
      showToast((error as Error).message || "Не удалось войти", "error");
    }
  };

  return (
    <>
      <AnimatePresence mode="wait">
        {!token ? (
          <motion.div
            key="login"
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0, transition: { duration: 0.9, ease: EASE } }}
            exit={{ opacity: 0, x: -40, transition: { duration: 0.5, ease: EASE } }}
          >
            <LoginPage
              onLogin={handleLogin}
              onRegister={handleRegister}
              onToast={(message, isError) => showToast(message, isError ? "error" : "success")}
            />
          </motion.div>
        ) : (
          <motion.div
            key="shell"
            initial={{ opacity: 0, x: 60 }}
            animate={{ opacity: 1, x: 0, transition: { duration: 0.9, ease: EASE } }}
            exit={{ opacity: 0, x: -60, transition: { duration: 0.5, ease: EASE } }}
            className="min-h-screen bg-white text-slate-900"
          >
            <div className="flex min-h-screen">
              <aside className="relative flex w-[280px] shrink-0 flex-col border-r border-neutral-100 bg-white px-6 pb-8 pt-8 shadow-[12px_0_40px_-32px_rgba(0,0,0,0.15)]">
                <div className="flex items-center justify-between">
                  <div className="text-lg font-semibold tracking-tight text-neutral-900">Funpay Automation</div>
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-neutral-200 bg-neutral-50 text-neutral-500">
                    ←
                  </div>
                </div>
                <nav className="mt-8 space-y-2">
                  {NAV_ITEMS.map((item, index) => (
                    <a
                      key={item.id}
                      href={`#${item.id}`}
                      className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition ${
                        index === 0
                          ? "bg-neutral-900 text-white shadow-lg shadow-neutral-900/20"
                          : "text-neutral-600 hover:bg-neutral-100"
                      }`}
                    >
                      <span className="text-base">{item.icon}</span>
                      <span className="truncate">{item.label}</span>
                    </a>
                  ))}
                </nav>
                <div className="mt-auto">
                  <button className="flex w-full items-center justify-center gap-2 rounded-2xl border border-neutral-200 bg-neutral-50 px-4 py-3 text-sm font-semibold text-neutral-700 transition hover:border-neutral-300 hover:bg-neutral-100">
                    <span>❔</span>
                    <span>Поддержка</span>
                  </button>
                </div>
              </aside>
              <main className="flex-1 bg-white">
                <div className="px-10 py-10 text-lg font-semibold text-neutral-400">Скоро тут будет контент</div>
              </main>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <Toast toast={toast} />
    </>
  );
};

export default App;
