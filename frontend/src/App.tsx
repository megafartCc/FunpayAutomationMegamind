import React, { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Toast from "./components/common/Toast";
import LoginPage from "./pages/LoginPage";
import { createApiClient } from "./services/api";
import { useToast } from "./hooks/useToast";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

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
            <div className="px-10 py-8 text-lg font-semibold">Funpay Automation</div>
          </motion.div>
        )}
      </AnimatePresence>
      <Toast toast={toast} />
    </>
  );
};

export default App;
