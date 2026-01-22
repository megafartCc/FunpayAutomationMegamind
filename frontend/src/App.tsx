import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Sidebar from "./components/layout/Sidebar";
import Section from "./components/layout/Section";
import StatsOverview from "./components/stats/StatsOverview";
import ActiveRentalsTable from "./components/rentals/ActiveRentalsTable";
import InventoryTable from "./components/inventory/InventoryTable";
import LotsPanel from "./components/lots/LotsPanel";
import ChatPanel from "./components/chats/ChatPanel";
import ManageAccountPanel from "./components/manage/ManageAccountPanel";
import AddAccountForm from "./components/account/AddAccountForm";
import NotificationsPanel from "./components/notifications/NotificationsPanel";
import SettingsPanel from "./components/settings/SettingsPanel";
import AuthOverlay from "./components/auth/AuthOverlay";
import Toast from "./components/common/Toast";
import { createApiClient } from "./services/api";
import { useInterval } from "./hooks/useInterval";
import { useToast } from "./hooks/useToast";
import {
  Account,
  Chat,
  ChatMessage,
  HealthStatus,
  Lot,
  NotificationItem,
  Rental,
  Stats,
} from "./types";

const CHAT_HISTORY_LIMIT = 60;

const App: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [rentals, setRentals] = useState<Rental[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [showPasswords, setShowPasswords] = useState(false);
  const [chats, setChats] = useState<Chat[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null);
  const [chatSearch, setChatSearch] = useState("");
  const [chatTitle, setChatTitle] = useState("Выберите чат");
  const [chatSubtitle, setChatSubtitle] = useState("Загрузите историю.");
  const [token, setToken] = useState(() => sessionStorage.getItem("adminToken") || "");
  const [authVisible, setAuthVisible] = useState(!sessionStorage.getItem("adminToken"));
  const [tick, setTick] = useState(0);

  const matchStartCache = useRef<Map<string, number>>(new Map());
  const chatHistoryCache = useRef<Map<number, ChatMessage[]>>(new Map());
  const chatHistoryRequestId = useRef(0);

  const { toast, showToast } = useToast();

  const api = useMemo(
    () =>
      createApiClient({
        getToken: () => token,
        onUnauthorized: () => {
          sessionStorage.removeItem("adminToken");
          sessionStorage.removeItem("adminUser");
          setToken("");
          setAuthVisible(true);
        },
      }),
    [token]
  );

  const apiFetch = api.apiFetch;

  const selectedAccount = useMemo(
    () => accounts.find((acc) => acc.id === selectedAccountId) || null,
    [accounts, selectedAccountId]
  );

  const loadHealth = useCallback(async () => {
    const data = await apiFetch<HealthStatus>("/api/health");
    setHealth(data);
  }, [apiFetch]);

  const loadStats = useCallback(async () => {
    const data = await apiFetch<Stats>("/api/stats");
    setStats(data);
  }, [apiFetch]);

  const loadNotifications = useCallback(async () => {
    const data = await apiFetch<{ items: NotificationItem[] }>("/api/notifications?limit=50");
    setNotifications(data.items || []);
  }, [apiFetch]);

  const loadLots = useCallback(async () => {
    const data = await apiFetch<{ items: Lot[] }>("/api/lots");
    setLots(data.items || []);
  }, [apiFetch]);

  const loadAccounts = useCallback(async () => {
    const data = await apiFetch<{ items: Account[] }>("/api/accounts?include_steamid=1");
    setAccounts(data.items || []);
  }, [apiFetch]);

  const loadActiveRentals = useCallback(
    async (expand = false) => {
      const params = new URLSearchParams();
      if (expand) {
        params.set("expand", "presence,chat");
        params.set("fast", "0");
      } else {
        params.set("fast", "1");
      }
      const data = await apiFetch<{ items: Rental[] }>(`/api/rentals/active?${params.toString()}`);
      setRentals(data.items || []);
    },
    [apiFetch]
  );

  const loadChats = useCallback(
    async (refresh = false) => {
      const params = new URLSearchParams({ fast: "1" });
      if (refresh) params.set("refresh", "1");
      const data = await apiFetch<{ items: Chat[] }>(`/api/chats?${params.toString()}`);
      setChats(data.items || []);
    },
    [apiFetch]
  );

  const loadChatHistory = useCallback(
    async (refresh = false, silent = false) => {
      if (!selectedChatId) {
        return;
      }
      const requestId = ++chatHistoryRequestId.current;
      const params = new URLSearchParams({ fast: "1", limit: String(CHAT_HISTORY_LIMIT) });
      if (refresh) params.set("refresh", "1");
      try {
        const data = await apiFetch<{ items: ChatMessage[] }>(
          `/api/chats/${selectedChatId}/history?${params.toString()}`
        );
        const items = data.items || [];
        chatHistoryCache.current.set(selectedChatId, items);
        if (requestId === chatHistoryRequestId.current) {
          setChatMessages(items);
        }
      } catch (error) {
        if (!silent) {
          showToast((error as Error).message || "Не удалось загрузить историю", "error");
        }
      }
    },
    [apiFetch, selectedChatId, showToast]
  );

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);

  const loadAll = useCallback(async () => {
    await Promise.all([
      loadHealth(),
      loadStats(),
      loadNotifications(),
      loadLots(),
      loadAccounts(),
      loadActiveRentals(false),
      loadChats(true),
    ]);
    setTimeout(() => {
      loadActiveRentals(true).catch(() => {});
    }, 200);
  }, [loadHealth, loadStats, loadNotifications, loadLots, loadAccounts, loadActiveRentals, loadChats]);

  useEffect(() => {
    if (!token) {
      setAuthVisible(true);
      return;
    }
    setAuthVisible(false);
    loadAll().catch((error) => showToast((error as Error).message || "Не удалось загрузить данные", "error"));
  }, [token, loadAll, showToast]);

  useInterval(() => {
    if (token) {
      loadAll().catch(() => {});
    }
  }, token ? 30000 : null);

  useInterval(() => {
    if (token) {
      loadChats(true).catch(() => {});
    }
  }, token ? 5000 : null);

  useInterval(() => {
    if (selectedChatId) {
      loadChatHistory(true, true);
    }
  }, selectedChatId ? 2000 : null);

  useInterval(() => setTick((prev) => prev + 1), 1000);

  const handleChatSelect = (chatId: number) => {
    setSelectedChatId(chatId);
    const chat = chats.find((c) => c.id === chatId);
    setChatTitle(chat?.name || "Чат");
    setChatSubtitle(`ID чата: ${chatId}`);
    const cached = chatHistoryCache.current.get(chatId);
    if (cached?.length) {
      setChatMessages(cached);
    } else {
      setChatMessages([]);
    }
    loadChatHistory(true).catch(() => {});
  };

  const handleSendChatMessage = async (text: string) => {
    if (!selectedChatId) {
      showToast("Сначала выберите чат.", "error");
      return;
    }
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      text,
      author: "Вы",
      chat_id: selectedChatId,
      by_bot: true,
    };
    const cached = chatHistoryCache.current.get(selectedChatId) || [];
    const next = [...cached, optimistic];
    chatHistoryCache.current.set(selectedChatId, next);
    setChatMessages(next);
    try {
      await apiFetch(`/api/chats/${selectedChatId}/send`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      showToast("Сообщение отправлено.");
      loadChatHistory(true, true);
      setChats((prev) =>
        prev.map((chat) =>
          chat.id === selectedChatId
            ? { ...chat, last_message_text: text, unread: false }
            : chat
        )
      );
    } catch (error) {
      const rollback = (chatHistoryCache.current.get(selectedChatId) || []).filter(
        (msg) => msg.id !== optimistic.id
      );
      chatHistoryCache.current.set(selectedChatId, rollback);
      setChatMessages(rollback);
      showToast((error as Error).message || "Не удалось отправить сообщение", "error");
    }
  };

  const handleCreateAccount = async (payload: Record<string, unknown>) => {
    await apiFetch("/api/accounts", { method: "POST", body: JSON.stringify(payload) });
    await loadAll();
  };

  const handleUpdateAccount = async (payload: Record<string, unknown>) => {
    if (!selectedAccountId) return;
    await apiFetch(`/api/accounts/${selectedAccountId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await loadAll();
  };

  const handleAssignAccount = async (owner: string) => {
    if (!selectedAccountId) return;
    await apiFetch(`/api/accounts/${selectedAccountId}/assign`, {
      method: "POST",
      body: JSON.stringify({ owner }),
    });
    await loadAll();
  };

  const handleExtendOwner = async (owner: string, hours: number, minutes: number) => {
    await apiFetch(`/api/rentals/user/${encodeURIComponent(owner)}/extend`, {
      method: "POST",
      body: JSON.stringify({ hours, minutes }),
    });
    await loadAll();
  };

  const handleReleaseAccount = async () => {
    if (!selectedAccountId) return;
    await apiFetch(`/api/accounts/${selectedAccountId}/release`, { method: "POST" });
    await loadAll();
  };

  const handleExtendAccount = async (hours: number, minutes: number) => {
    if (!selectedAccountId) return;
    await apiFetch(`/api/accounts/${selectedAccountId}/extend`, {
      method: "POST",
      body: JSON.stringify({ hours, minutes }),
    });
    await loadAll();
  };

  const handleDeauth = async () => {
    if (!selectedAccountId) return;
    await apiFetch(`/api/accounts/${selectedAccountId}/steam/deauthorize`, { method: "POST" });
  };

  const handleChangePassword = async (newPassword?: string | null) => {
    if (!selectedAccountId) return null;
    const result = await apiFetch<{ new_password?: string }>(
      `/api/accounts/${selectedAccountId}/steam/password`,
      {
        method: "POST",
        body: JSON.stringify({ new_password: newPassword || null }),
      }
    );
    const password = result?.new_password || null;
    if (password) {
      const selected = accounts.find((account) => account.id === selectedAccountId);
      setAccounts((prev) =>
        prev.map((account) => {
          if (account.id === selectedAccountId) return { ...account, password };
          if (selected?.login && account.login === selected.login) {
            return { ...account, password };
          }
          return account;
        })
      );
    }
    return password;
  };

  const handleDeleteAccount = async () => {
    if (!selectedAccountId) return;
    await apiFetch(`/api/accounts/${selectedAccountId}`, { method: "DELETE" });
    setSelectedAccountId(null);
    await loadAll();
  };

  const handleCreateLot = async (payload: { lot_number: number; account_id: number; lot_url?: string | null }) => {
    await apiFetch("/api/lots", { method: "POST", body: JSON.stringify(payload) });
    await loadAll();
  };

  const handleDeleteLot = async (lotNumber: number) => {
    await apiFetch(`/api/lots/${lotNumber}`, { method: "DELETE" });
    await loadAll();
  };

  const handleUpdateGoldenKey = async (key: string) => {
    await apiFetch("/api/auth/golden-key", {
      method: "PUT",
      body: JSON.stringify({ golden_key: key }),
    });
  };

  const handleLogout = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore
    }
    sessionStorage.removeItem("adminToken");
    sessionStorage.removeItem("adminUser");
    setToken("");
    setAuthVisible(true);
  };

  const handleRegister = async (payload: { username: string; password: string; golden_key: string }) => {
    try {
      const data = await apiFetch<{ token: string; username: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      sessionStorage.setItem("adminToken", data.token);
      sessionStorage.setItem("adminUser", data.username);
      setToken(data.token);
      setAuthVisible(false);
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
      setAuthVisible(false);
      showToast("Вход выполнен.");
    } catch (error) {
      showToast((error as Error).message || "Не удалось войти", "error");
    }
  };

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <Sidebar health={health} onRefreshAll={() => loadAll().catch(() => {})} />
      <main className="flex-1 space-y-10 px-8 py-10">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Панель управления</h1>
          <p className="text-sm text-slate-400">
            Управляйте арендами, инвентарём, лотами, чатами и автоматизацией.
          </p>
        </header>

        <Section id="overview" title="Обзор" subtitle="Ключевые показатели.">
          <StatsOverview stats={stats} />
        </Section>

        <Section id="rentals" title="Активные аренды" subtitle="Текущие аренды и тайминг.">
          <ActiveRentalsTable rentals={rentals} tick={tick} matchStartCache={matchStartCache} />
        </Section>

        <Section id="inventory" title="Инвентарь" subtitle="Все аккаунты в наличии. Нажмите строку для управления.">
          <div className="mb-4 flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={showPasswords}
                onChange={(event) => setShowPasswords(event.target.checked)}
              />
              Показать пароли
            </label>
            <input
              className="input w-full max-w-sm"
              type="search"
              placeholder="Фильтр по названию или логину"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <InventoryTable
            accounts={accounts}
            selectedId={selectedAccountId}
            search={search}
            showPasswords={showPasswords}
            onSelect={setSelectedAccountId}
          />
        </Section>

        <Section id="lots" title="Лоты" subtitle="Связка лотов с аккаунтами.">
          <LotsPanel
            lots={lots}
            accounts={accounts}
            onCreate={handleCreateLot}
            onDelete={handleDeleteLot}
            onToast={(message, isError) => showToast(message, isError ? "error" : "success")}
          />
        </Section>

        <Section id="chats" title="Чаты FunPay" subtitle="Диалоги с покупателями.">
          <ChatPanel
            chats={chats}
            chatSearch={chatSearch}
            selectedChatId={selectedChatId}
            chatTitle={chatTitle}
            chatSubtitle={chatSubtitle}
            messages={chatMessages}
            onSearchChange={setChatSearch}
            onRefresh={() => loadChats(true).catch(() => {})}
            onLoadHistory={() => loadChatHistory(true).catch(() => {})}
            onSelectChat={handleChatSelect}
            onSendMessage={handleSendChatMessage}
          />
        </Section>

        <Section id="manage" title="Управление аккаунтом" subtitle="Редактируйте аккаунты и запускайте действия.">
          <ManageAccountPanel
            account={selectedAccount}
            onUpdate={handleUpdateAccount}
            onAssign={handleAssignAccount}
            onExtendOwner={handleExtendOwner}
            onRelease={handleReleaseAccount}
            onExtend={handleExtendAccount}
            onDeauth={handleDeauth}
            onChangePassword={handleChangePassword}
            onDelete={handleDeleteAccount}
            onToast={(message, isError) => showToast(message, isError ? "error" : "success")}
          />
        </Section>

        <Section id="add" title="Добавить аккаунт" subtitle="Добавьте новый аккаунт в инвентарь.">
          <AddAccountForm onSubmit={handleCreateAccount} onToast={(message, isError) => showToast(message, isError ? "error" : "success")} />
        </Section>

        <Section id="notifications" title="Уведомления" subtitle="Системные сообщения и события бота.">
          <NotificationsPanel notifications={notifications} />
        </Section>

        <Section id="settings" title="Настройки" subtitle="Управление золотым ключом и сессией.">
          <SettingsPanel
            onUpdateGoldenKey={handleUpdateGoldenKey}
            onLogout={handleLogout}
            onToast={(message, isError) => showToast(message, isError ? "error" : "success")}
          />
        </Section>
      </main>

      <AuthOverlay
        visible={authVisible}
        onRegister={handleRegister}
        onLogin={handleLogin}
        onToast={(message, isError) => showToast(message, isError ? "error" : "success")}
      />

      <Toast toast={toast} />
    </div>
  );
};

export default App;
