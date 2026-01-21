const ui = {
  health: document.getElementById("healthStatus"),
  total: document.getElementById("statTotal"),
  active: document.getElementById("statActive"),
  available: document.getElementById("statAvailable"),
  recent: document.getElementById("statRecent"),
  activeTable: document.getElementById("activeRentals"),
  inventoryTable: document.getElementById("inventoryTable"),
  notifications: document.getElementById("notificationsList"),
  refreshAll: document.getElementById("refreshAll"),
  search: document.getElementById("searchAccounts"),
  showPasswords: document.getElementById("showPasswords"),
  toast: document.getElementById("toast"),
  chats: {
    list: document.getElementById("chatList"),
    search: document.getElementById("chatSearch"),
    refresh: document.getElementById("refreshChats"),
    loadHistory: document.getElementById("loadHistory"),
    title: document.getElementById("chatTitle"),
    subtitle: document.getElementById("chatSubtitle"),
    messages: document.getElementById("chatMessages"),
    form: document.getElementById("chatSendForm"),
    input: document.getElementById("chatMessageInput"),
  },
  manage: {
    id: document.getElementById("manageId"),
    name: document.getElementById("manageName"),
    login: document.getElementById("manageLogin"),
    password: document.getElementById("managePassword"),
    maFileJson: document.getElementById("manageMaFileJson"),
    duration: document.getElementById("manageDuration"),
    durationMinutes: document.getElementById("manageDurationMinutes"),
    owner: document.getElementById("manageOwner"),
    start: document.getElementById("manageStart"),
    update: document.getElementById("updateAccount"),
    assign: document.getElementById("assignAccount"),
    release: document.getElementById("releaseAccount"),
    steamDeauth: document.getElementById("steamDeauth"),
    steamNewPassword: document.getElementById("steamNewPassword"),
    steamChangePassword: document.getElementById("steamChangePassword"),
    extend: document.getElementById("extendAccount"),
    extendHours: document.getElementById("extendHours"),
    extendMinutes: document.getElementById("extendMinutes"),
    extendOwner: document.getElementById("extendOwner"),
    extendOwnerHours: document.getElementById("extendOwnerHours"),
    extendOwnerMinutes: document.getElementById("extendOwnerMinutes"),
    delete: document.getElementById("deleteAccount"),
  },
  addForm: document.getElementById("addAccountForm"),
  addStatus: document.getElementById("addStatus"),
  lots: {
    form: document.getElementById("lotForm"),
    number: document.getElementById("lotNumber"),
    account: document.getElementById("lotAccount"),
    url: document.getElementById("lotUrl"),
    table: document.getElementById("lotsTable"),
  },
  auth: {
    overlay: document.getElementById("authOverlay"),
    registerForm: document.getElementById("registerForm"),
    loginForm: document.getElementById("loginForm"),
    regUsername: document.getElementById("regUsername"),
    regPassword: document.getElementById("regPassword"),
    regGoldenKey: document.getElementById("regGoldenKey"),
    loginUsername: document.getElementById("loginUsername"),
    loginPassword: document.getElementById("loginPassword"),
  },
};

let accountsCache = [];
let selectedId = null;
let chatsCache = [];
let selectedChatId = null;
let chatHistoryCache = new Map();
let chatPollTimer = null;
let chatListTimer = null;
let chatHistoryRequestId = 0;
let chatListInFlight = false;
const chatHistoryInFlight = new Set();
const rentalsInFlight = new Set();

const CHAT_HISTORY_LIMIT = 60;
const CHAT_POLL_INTERVAL = 2000;
const CHAT_LIST_POLL_INTERVAL = 5000;

const toast = (message, isError = false) => {
  ui.toast.textContent = message;
  ui.toast.style.borderColor = isError ? "rgba(242, 95, 92, 0.6)" : "rgba(242, 176, 90, 0.4)";
  ui.toast.classList.add("show");
  setTimeout(() => ui.toast.classList.remove("show"), 2800);
};

const getAdminKey = () => sessionStorage.getItem("adminToken") || "";

const loadUsers = () => [];
const saveUsers = () => {};

const showAuth = (message) => {
  if (message) {
    toast(message, true);
  }
  ui.auth.overlay.classList.remove("hidden");
};

const hideAuth = () => {
  ui.auth.overlay.classList.add("hidden");
};

const apiFetch = async (path, options = {}) => {
  const headers = options.headers ? { ...options.headers } : {};
  headers["Content-Type"] = "application/json";
  const adminToken = getAdminKey();
  if (adminToken) {
    headers["Authorization"] = `Bearer ${adminToken}`;
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401) {
      sessionStorage.removeItem("adminToken");
      showAuth("Пожалуйста, войдите.");
    }
    const contentType = response.headers.get("content-type") || "";
    let message = "";
    if (contentType.includes("application/json")) {
      try {
        const data = await response.json();
        if (typeof data?.detail === "string") {
          message = data.detail;
        } else if (data?.detail != null) {
          message = JSON.stringify(data.detail);
        } else {
          message = JSON.stringify(data);
        }
      } catch (error) {
        message = "Запрос не выполнен";
      }
    } else {
      message = await response.text();
    }
    throw new Error(message || "Запрос не выполнен");
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
};

const formatDate = (value) => {
  if (!value) return "-";
  const parsed = new Date(value.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
};

const getDurationMinutes = (item) => {
  if (!item) return 0;
  const minutes = Number(item.rental_duration_minutes);
  if (Number.isFinite(minutes) && minutes > 0) {
    return minutes;
  }
  const hours = Number(item.rental_duration || 0);
  if (!Number.isFinite(hours)) return 0;
  return hours * 60;
};

const formatDuration = (item) => {
  const totalMinutes = getDurationMinutes(item);
  if (!totalMinutes) return "-";
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours && minutes) return `${hours}ч ${minutes}м`;
  if (hours) return `${hours}ч`;
  return `${minutes}м`;
};

const formatRentalEnd = (start, durationMinutes) => {
  if (!start || !durationMinutes) return "-";
  const parsed = new Date(start.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) {
    return "-";
  }
  parsed.setMinutes(parsed.getMinutes() + Number(durationMinutes));
  return parsed.toLocaleString();
};

const escapeHtml = (value) => {
  if (!value) return "";
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
};

const setManagePanel = (account) => {
  if (!account) {
    ui.manage.id.value = "";
    ui.manage.name.value = "";
    ui.manage.login.value = "";
    ui.manage.password.value = "";
    ui.manage.maFileJson.value = "";
    ui.manage.duration.value = "";
    ui.manage.durationMinutes.value = "";
    ui.manage.owner.value = "";
    ui.manage.start.value = "";
    return;
  }

  ui.manage.id.value = account.id;
  ui.manage.name.value = account.account_name || "";
  ui.manage.login.value = account.login || "";
  ui.manage.password.value = account.password || "";
  ui.manage.maFileJson.value = "";
  const totalMinutes = getDurationMinutes(account);
  ui.manage.duration.value = Number.isFinite(totalMinutes) ? Math.floor(totalMinutes / 60) : "";
  ui.manage.durationMinutes.value = Number.isFinite(totalMinutes) ? totalMinutes % 60 : "";
  ui.manage.owner.value = account.owner || "";
  ui.manage.start.value = formatDate(account.rental_start);
};

const renderStats = (stats) => {
  ui.total.textContent = stats.total_accounts ?? 0;
  ui.active.textContent = stats.active_rentals ?? 0;
  ui.available.textContent = stats.available_accounts ?? 0;
  ui.recent.textContent = stats.recent_rentals ?? 0;
};

const renderHealth = (status) => {
  if (status?.funpay_ready) {
    ui.health.textContent = "FunPay готов";
  } else if (status?.funpay_enabled) {
    ui.health.textContent = "FunPay запускается";
  } else {
    ui.health.textContent = "FunPay отключен";
  }
};

const PRESENCE_BASE_URL = "https://laudable-flow-production-9c8a.up.railway.app/presence";

const presenceLabel = (item) => {
  if (item?.presence_label) return item.presence_label;
  if (item?.in_match) {
    const extras = [];
    if (item?.hero_name) extras.push(item.hero_name);
    if (item?.match_time) extras.push(item.match_time);
    return extras.length ? `В матче(${extras.join(")(")})` : "В матче";
  }
  if (item?.in_game) return "В игре";
  return "Оффлайн";
};

const presenceLink = (item) => {
  const label = escapeHtml(presenceLabel(item));
  if (!item?.steamid) return label;
  const url = `${PRESENCE_BASE_URL}/${item.steamid}`;
  return `<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`;
};

const ensureActiveStatusHeader = () => {
  const tbody = ui.activeTable;
  if (!tbody) return;
  const table = tbody.closest("table");
  const row = table?.querySelector("thead tr");
  if (!row) return;
  const headers = Array.from(row.querySelectorAll("th"));
  if (headers.some((th) => th.dataset.key === "status")) return;
  const statusTh = document.createElement("th");
  statusTh.textContent = "Статус";
  statusTh.dataset.key = "status";
  row.appendChild(statusTh);
};

const ensureActiveRentalsHeader = () => {
  const tbody = ui.activeTable;
  if (!tbody) return;
  const table = tbody.closest("table");
  const row = table?.querySelector("thead tr");
  if (!row) return;

  const headers = Array.from(row.querySelectorAll("th"));
  if (headers.some((th) => th.dataset.key === "chat" || th.textContent?.trim() === "Чат")) return;

  const insertBefore = headers[3] || null;
  const th = document.createElement("th");
  th.textContent = "Чат";
  th.dataset.key = "chat";
  row.insertBefore(th, insertBefore);
};

const renderActiveRentals = (items) => {
  ensureActiveRentalsHeader();
  ensureActiveStatusHeader?.();
  if (!items.length) {
    ui.activeTable.innerHTML = "<tr><td colspan=\"9\">Нет активных аренд.</td></tr>";
    return;
  }
  ui.activeTable.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.id}</td>
          <td>${item.account_name}</td>
          <td>${item.owner}</td>
          <td>${item.chat_url ? `<a href="${item.chat_url}" target="_blank" rel="noreferrer">${escapeHtml(item.chat_url)}</a>` : "-"}</td>
          <td>${item.login}</td>
          <td>${formatDate(item.rental_start)}</td>
          <td>${formatRentalEnd(item.rental_start, getDurationMinutes(item))}</td>
          <td>${formatDuration(item)}</td>
          <td>${presenceLink(item)}</td>
        </tr>
      `
    )
    .join("");
};

const renderInventory = (items) => {
  const query = ui.search.value.trim().toLowerCase();
  const filtered = items.filter((item) => {
    const name = item.account_name?.toLowerCase() || "";
    const login = item.login?.toLowerCase() || "";
    return !query || name.includes(query) || login.includes(query);
  });

  if (!filtered.length) {
    ui.inventoryTable.innerHTML = "<tr><td colspan=\"5\">Аккаунты не найдены.</td></tr>";
    return;
  }

  const showPasswords = ui.showPasswords.checked;

  ui.inventoryTable.innerHTML = filtered
    .map(
      (item) => `
        <tr data-id="${item.id}">
          <td>${item.id}</td>
          <td>${item.account_name}</td>
          <td>${item.login}</td>
          <td>${showPasswords ? item.password : "******"}</td>
          <td>${item.steamid || "-"}</td>
        </tr>
      `
    )
    .join("");

  document.querySelectorAll("#inventoryTable tr").forEach((row) => {
    row.addEventListener("click", () => {
      selectedId = Number(row.dataset.id);
      const account = accountsCache.find((acc) => acc.id === selectedId);
      setManagePanel(account);
      document.querySelectorAll("#inventoryTable tr").forEach((item) => {
        item.classList.toggle("selected", Number(item.dataset.id) === selectedId);
      });
    });
  });
};

const renderLotSelect = (accounts) => {
  if (!ui.lots.account) return;
  const options = accounts
    .map(
      (account) =>
        `<option value="${account.id}">${escapeHtml(account.account_name)} (ID ${account.id})</option>`
    )
    .join("");
  ui.lots.account.innerHTML = `<option value="">Выберите аккаунт</option>${options}`;
};

const renderLots = (lots) => {
  if (!ui.lots.table) return;
  if (!lots.length) {
    ui.lots.table.innerHTML = "<tr><td colspan=\"4\">Лоты не настроены.</td></tr>";
    return;
  }
  ui.lots.table.innerHTML = lots
    .map((lot) => {
      const url = lot.lot_url ? escapeHtml(lot.lot_url) : "";
      const link = url ? `<a href="${url}" target="_blank" rel="noreferrer">${url}</a>` : "-";
      return `
        <tr>
          <td>№${lot.lot_number}</td>
          <td>${escapeHtml(lot.account_name)} (ID ${lot.account_id})</td>
          <td>${link}</td>
          <td>
            <button class="btn ghost" data-lot="${lot.lot_number}">Удалить</button>
          </td>
        </tr>
      `;
    })
    .join("");
};
const renderNotifications = (items) => {
  if (!items.length) {
    ui.notifications.innerHTML = "<div class=\"notice\"><h4>Уведомлений нет</h4><p>Системные события появятся здесь.</p></div>";
    return;
  }
  ui.notifications.innerHTML = items
    .map(
      (item) => `
        <div class="notice">
          <h4>${item.level?.toUpperCase() || "ИНФО"} - ${formatDate(item.created_at)}</h4>
          <p>${escapeHtml(item.message)}</p>
          <p>Владелец: ${item.owner || "-"} | Аккаунт: ${item.account_id || "-"}</p>
        </div>
      `
    )
    .join("");
};

const renderChatList = (items) => {
  const query = ui.chats.search.value.trim().toLowerCase();
  const filtered = items.filter((chat) => {
    const name = chat.name?.toLowerCase() || "";
    const last = chat.last_message_text?.toLowerCase() || "";
    return !query || name.includes(query) || last.includes(query);
  });

  if (!filtered.length) {
    ui.chats.list.innerHTML = "<div class=\"notice\"><h4>Чатов нет</h4><p>Чаты не найдены.</p></div>";
    return;
  }

  ui.chats.list.innerHTML = filtered
    .map(
      (chat) => `
        <button class="chat-item ${chat.id === selectedChatId ? "active" : ""}" data-id="${chat.id}">
          <div>
            <h4>${escapeHtml(chat.name || "Без имени")}</h4>
            <p>${escapeHtml(chat.last_message_text || "")}</p>
          </div>
          ${chat.unread ? '<span class="badge">новое</span>' : ''}
        </button>
      `
    )
    .join("");

  document.querySelectorAll(".chat-item").forEach((item) => {
    item.addEventListener("click", () => {
      selectedChatId = Number(item.dataset.id);
      const chat = chatsCache.find((c) => c.id === selectedChatId);
      ui.chats.title.textContent = chat?.name || "Чат";
      ui.chats.subtitle.textContent = `ID чата: ${selectedChatId}`;
      ui.chats.list.querySelectorAll(".chat-item").forEach((row) => {
        row.classList.toggle("active", Number(row.dataset.id) === selectedChatId);
      });
      const cached = getCachedChatHistory(selectedChatId);
      if (cached.length) {
        renderChatMessages(cached);
      }
      loadChatHistory({ refresh: true });
      startChatPolling();
    });
  });
};

const renderChatMessages = (items) => {
  if (!items.length) {
    ui.chats.messages.innerHTML = "<div class=\"notice\"><h4>Сообщений нет</h4><p>Выберите чат, чтобы загрузить историю.</p></div>";
    return;
  }

  ui.chats.messages.innerHTML = items
    .map((message) => {
      const author = message.author || "Неизвестно";
      const text = escapeHtml(message.text || "");
      const image = message.image_link
        ? `<a href="${message.image_link}" target="_blank" rel="noreferrer">Открыть изображение</a>`
        : "";
      const type = message.type ? `(${message.type})` : "";
      return `
        <div class="chat-message ${message.by_bot ? "self" : ""}">
          <h5>${escapeHtml(author)} ${type}</h5>
          <p>${text || "(без текста)"}</p>
          ${image}
        </div>
      `;
    })
    .join("");
};

const renderChatLoading = (label = "Загружаем историю чата...") => {
  ui.chats.messages.innerHTML = `
    <div class="notice">
      <h4>Загрузка</h4>
      <p>${escapeHtml(label)}</p>
    </div>
  `;
};

const getCachedChatHistory = (chatId) => chatHistoryCache.get(chatId) || [];

const setCachedChatHistory = (chatId, items) => {
  chatHistoryCache.set(chatId, items || []);
};

const stopChatPolling = () => {
  if (chatPollTimer) {
    clearInterval(chatPollTimer);
    chatPollTimer = null;
  }
};

const startChatPolling = () => {
  stopChatPolling();
  if (!selectedChatId) return;
  chatPollTimer = setInterval(() => {
    loadChatHistory({ refresh: true, silent: true });
  }, CHAT_POLL_INTERVAL);
};

const startChatListPolling = () => {
  if (chatListTimer) {
    clearInterval(chatListTimer);
  }
  chatListTimer = setInterval(() => {
    loadChats({ refresh: true, silent: true });
  }, CHAT_LIST_POLL_INTERVAL);
};


const loadChats = async ({ refresh = false, silent = false } = {}) => {
  if (chatListInFlight) return;
  chatListInFlight = true;
  try {
    const params = new URLSearchParams({ fast: "1" });
    if (refresh) {
      params.set("refresh", "1");
    }
    const data = await apiFetch(`/api/chats?${params.toString()}`);
    chatsCache = data.items || [];
    renderChatList(chatsCache);
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось загрузить чаты", true);
    }
  } finally {
    chatListInFlight = false;
  }
};

const loadChatHistory = async ({ refresh = false, silent = false } = {}) => {
  if (!selectedChatId) {
    ui.chats.messages.innerHTML = "<div class=\"notice\"><h4>Выберите чат</h4><p>Выберите чат, чтобы просмотреть сообщения.</p></div>";
    return;
  }
  const chatId = selectedChatId;
  const cached = getCachedChatHistory(chatId);
  if (chatHistoryInFlight.has(chatId)) {
    if (!cached.length) {
      renderChatLoading();
    }
    return;
  }
  chatHistoryInFlight.add(chatId);
  const requestId = ++chatHistoryRequestId;
  if (cached.length) {
    renderChatMessages(cached);
  } else {
    renderChatLoading();
  }
  try {
    const params = new URLSearchParams({
      fast: "1",
      limit: String(CHAT_HISTORY_LIMIT),
    });
    if (refresh) {
      params.set("refresh", "1");
    }
    const data = await apiFetch(`/api/chats/${chatId}/history?${params.toString()}`);
    const items = data.items || [];
    setCachedChatHistory(chatId, items);
    if (requestId !== chatHistoryRequestId || chatId !== selectedChatId) return;
    renderChatMessages(items);
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось загрузить историю", true);
    }
  } finally {
    chatHistoryInFlight.delete(chatId);
  }
};

const loadHealth = async ({ silent = false } = {}) => {
  try {
    const data = await apiFetch("/api/health");
    renderHealth(data);
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось обновить статус", true);
    }
  }
};

const loadStats = async ({ silent = false } = {}) => {
  try {
    const data = await apiFetch("/api/stats");
    renderStats(data);
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось загрузить статистику", true);
    }
  }
};

const loadNotifications = async ({ silent = false, limit = 50 } = {}) => {
  try {
    const data = await apiFetch(`/api/notifications?limit=${limit}`);
    renderNotifications(data.items || []);
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось загрузить уведомления", true);
    }
  }
};

const loadLots = async ({ silent = false } = {}) => {
  try {
    const data = await apiFetch("/api/lots");
    renderLots(data.items || []);
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось загрузить лоты", true);
    }
  }
};

const loadAccounts = async ({ silent = false } = {}) => {
  try {
    const data = await apiFetch("/api/accounts");
    accountsCache = data.items || [];
    renderInventory(accountsCache);
    renderLotSelect(accountsCache);
    if (selectedId) {
      const selected = accountsCache.find((acc) => acc.id === selectedId);
      setManagePanel(selected || null);
    }
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось загрузить инвентарь", true);
    }
  }
};

const loadActiveRentals = async ({ expand = false, silent = false } = {}) => {
  const mode = expand ? "full" : "fast";
  if (rentalsInFlight.has(mode)) return;
  rentalsInFlight.add(mode);
  try {
    const params = new URLSearchParams();
    if (expand) {
      params.set("expand", "presence,chat");
      params.set("fast", "0");
    } else {
      params.set("fast", "1");
    }
    const data = await apiFetch(`/api/rentals/active?${params.toString()}`);
    renderActiveRentals(data.items || []);
  } catch (error) {
    if (!silent) {
      toast(error.message || "Не удалось загрузить активные аренды", true);
    }
  } finally {
    rentalsInFlight.delete(mode);
  }
};

const loadAll = async () => {
  loadHealth();
  loadStats();
  loadNotifications();
  loadLots();
  loadAccounts();
  loadActiveRentals({ expand: false });
  setTimeout(() => {
    loadActiveRentals({ expand: true, silent: true });
  }, 200);
  loadChats({ refresh: true });
  startChatListPolling();
};

ui.refreshAll.addEventListener("click", () => {
  loadAll();
});

let autoRefresh = null;
const startAutoRefresh = () => {
  if (autoRefresh) clearInterval(autoRefresh);
  autoRefresh = setInterval(() => {
    if (getAdminKey()) {
      loadAll().catch(() => {});
    }
  }, 30000);
};

ui.search.addEventListener("input", () => renderInventory(accountsCache));
ui.showPasswords.addEventListener("change", () => renderInventory(accountsCache));

ui.chats.search.addEventListener("input", () => renderChatList(chatsCache));
ui.chats.refresh.addEventListener("click", () => loadChats({ refresh: true }));
ui.chats.loadHistory.addEventListener("click", () => loadChatHistory({ refresh: true }));

ui.chats.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedChatId) {
    toast("Сначала выберите чат.", true);
    return;
  }
  const text = ui.chats.input.value.trim();
  if (!text) {
    toast("Введите сообщение.", true);
    return;
  }
  const chatId = selectedChatId;
  const optimistic = {
    id: `local-${Date.now()}`,
    text,
    author: "Вы",
    author_id: null,
    chat_id: chatId,
    chat_name: ui.chats.title.textContent || null,
    image_link: null,
    by_bot: true,
    by_vertex: false,
    type: null,
  };
  const cached = getCachedChatHistory(chatId);
  setCachedChatHistory(chatId, [...cached, optimistic]);
  renderChatMessages(getCachedChatHistory(chatId));
  const chat = chatsCache.find((c) => c.id === chatId);
  if (chat) {
    chat.last_message_text = text;
    chat.unread = false;
    renderChatList(chatsCache);
  }
  ui.chats.input.value = "";
  try {
    await apiFetch(`/api/chats/${chatId}/send`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    toast("Сообщение отправлено.");
    loadChatHistory({ refresh: true, silent: true });
  } catch (error) {
    const rollback = getCachedChatHistory(chatId).filter((msg) => msg.id !== optimistic.id);
    setCachedChatHistory(chatId, rollback);
    renderChatMessages(rollback);
    toast(error.message || "Не удалось отправить сообщение", true);
  }
});

ui.addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(ui.addForm);
  const payload = Object.fromEntries(formData.entries());
  delete payload.rental_duration;
  delete payload.owner;
  if (!payload.mafile_json) {
    delete payload.mafile_json;
  }
  try {
    await apiFetch("/api/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    ui.addForm.reset();
    toast("Аккаунт добавлен.");
    loadAll();
  } catch (error) {
    toast(error.message || "Не удалось добавить аккаунт", true);
  }
});

if (ui.lots.form) {
  ui.lots.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const lotNumber = Number(ui.lots.number.value || 0);
    const accountId = Number(ui.lots.account.value || 0);
    const lotUrl = ui.lots.url ? ui.lots.url.value.trim() : "";
    if (!lotNumber || !accountId) {
      toast("Укажите номер лота и аккаунт.", true);
      return;
    }
    try {
      await apiFetch("/api/lots", {
        method: "POST",
        body: JSON.stringify({ lot_number: lotNumber, account_id: accountId, lot_url: lotUrl || null }),
      });
      ui.lots.form.reset();
      toast("Лот сохранен.");
      loadAll();
    } catch (error) {
      toast(error.message || "Не удалось сохранить лот", true);
    }
  });
}

if (ui.lots.table) {
  ui.lots.table.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-lot]");
    if (!button) return;
    const lotNumber = Number(button.dataset.lot || 0);
    if (!lotNumber) return;
    try {
      await apiFetch(`/api/lots/${lotNumber}`, { method: "DELETE" });
      toast("Лот удален.");
      loadAll();
    } catch (error) {
      toast(error.message || "Не удалось удалить лот", true);
    }
  });
}

ui.manage.update.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Сначала выберите аккаунт.", true);
    return;
  }
  const durationHoursValue = ui.manage.duration.value.trim();
  const durationMinutesValue = ui.manage.durationMinutes.value.trim();
  const payload = {
    account_name: ui.manage.name.value.trim(),
    login: ui.manage.login.value.trim(),
    password: ui.manage.password.value.trim(),
    mafile_json: ui.manage.maFileJson.value.trim(),
  };
  if (durationHoursValue !== "" || durationMinutesValue !== "") {
    const hours = Number(durationHoursValue || 0);
    const minutes = Number(durationMinutesValue || 0);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
      toast("Длительность должна быть числом.", true);
      return;
    }
    if (hours < 0 || minutes < 0 || minutes > 59) {
      toast("Минуты должны быть от 0 до 59.", true);
      return;
    }
    if (hours === 0 && minutes === 0) {
      toast("Длительность должна быть больше 0.", true);
      return;
    }
    payload.rental_duration = hours;
    payload.rental_minutes = minutes;
  }
  if (!payload.mafile_json) {
    delete payload.mafile_json;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    toast("Аккаунт обновлён.");
    loadAll();
  } catch (error) {
    toast(error.message || "Не удалось обновить аккаунт", true);
  }
});

ui.manage.steamDeauth.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Сначала выберите аккаунт.", true);
    return;
  }
  try {
    toast("Деавторизация Steam запущена...");
    await apiFetch(`/api/accounts/${selectedId}/steam/deauthorize`, { method: "POST" });
    toast("Сессии Steam деавторизованы.");
  } catch (error) {
    toast(error.message || "Не удалось деавторизовать Steam", true);
  }
});

ui.manage.steamChangePassword.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Сначала выберите аккаунт.", true);
    return;
  }
  const newPassword = ui.manage.steamNewPassword.value.trim();
  try {
    toast("Смена пароля Steam...");
    const result = await apiFetch(`/api/accounts/${selectedId}/steam/password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword || null }),
    });
    const password = result?.new_password;
    if (password) {
      ui.manage.password.value = password;
      const selected = accountsCache.find((acc) => acc.id === selectedId);
      if (selected?.login) {
        accountsCache.forEach((acc) => {
          if (acc.login === selected.login) {
            acc.password = password;
          }
        });
      } else if (selected) {
        selected.password = password;
      }
      renderInventory(accountsCache);
      toast(`Пароль Steam изменён: ${password}`);
    } else {
      toast("Пароль Steam изменён.");
    }
  } catch (error) {
    toast(error.message || "Не удалось изменить пароль Steam", true);
  }
});

ui.manage.assign.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Сначала выберите аккаунт.", true);
    return;
  }
  const owner = ui.manage.owner.value.trim();
  if (!owner) {
    toast("Укажите владельца.", true);
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}/assign`, {
      method: "POST",
      body: JSON.stringify({ owner }),
    });
    toast("Владелец назначен.");
    loadAll();
  } catch (error) {
    toast(error.message || "Не удалось назначить владельца", true);
  }
});

ui.manage.extendOwner.addEventListener("click", async () => {
  const owner = ui.manage.owner.value.trim();
  if (!owner) {
    toast("Укажите владельца.", true);
    return;
  }
  const hoursValue = ui.manage.extendOwnerHours.value.trim();
  const minutesValue = ui.manage.extendOwnerMinutes.value.trim();
  if (hoursValue === "" && minutesValue === "") {
    toast("Укажите часы или минуты для продления.", true);
    return;
  }
  const hours = Number(hoursValue || 0);
  const minutes = Number(minutesValue || 0);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
    toast("Продление должно быть числом.", true);
    return;
  }
  if (hours < 0 || minutes < 0 || minutes > 59) {
    toast("Минуты должны быть от 0 до 59.", true);
    return;
  }
  if (hours === 0 && minutes === 0) {
    toast("Укажите часы или минуты для продления.", true);
    return;
  }
  try {
    await apiFetch(`/api/rentals/user/${encodeURIComponent(owner)}/extend`, {
      method: "POST",
      body: JSON.stringify({ hours, minutes }),
    });
    toast("Аренды владельца продлены.");
    ui.manage.extendOwnerHours.value = "";
    ui.manage.extendOwnerMinutes.value = "";
    loadAll();
  } catch (error) {
    toast(error.message || "Не удалось продлить аренды владельца", true);
  }
});

ui.manage.release.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Сначала выберите аккаунт.", true);
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}/release`, {
      method: "POST",
    });
    toast("Аккаунт освобождён.");
    loadAll();
  } catch (error) {
    toast(error.message || "Не удалось освободить аккаунт", true);
  }
});

ui.manage.extend.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Сначала выберите аккаунт.", true);
    return;
  }
  const hoursValue = ui.manage.extendHours.value.trim();
  const minutesValue = ui.manage.extendMinutes.value.trim();
  if (hoursValue === "" && minutesValue === "") {
    toast("Укажите часы или минуты для продления.", true);
    return;
  }
  const hours = Number(hoursValue || 0);
  const minutes = Number(minutesValue || 0);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
    toast("Продление должно быть числом.", true);
    return;
  }
  if (hours < 0 || minutes < 0 || minutes > 59) {
    toast("Минуты должны быть от 0 до 59.", true);
    return;
  }
  if (hours === 0 && minutes === 0) {
    toast("Укажите часы или минуты для продления.", true);
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}/extend`, {
      method: "POST",
      body: JSON.stringify({ hours, minutes }),
    });
    toast("Аренда продлена.");
    ui.manage.extendHours.value = "";
    ui.manage.extendMinutes.value = "";
    loadAll();
  } catch (error) {
    toast(error.message || "Не удалось продлить аренду", true);
  }
});

ui.manage.delete.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Сначала выберите аккаунт.", true);
    return;
  }
  if (!confirm("Удалить этот аккаунт?")) {
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}`, {
      method: "DELETE",
    });
    toast("Аккаунт удалён.");
    selectedId = null;
    setManagePanel(null);
    loadAll();
  } catch (error) {
    toast(error.message || "Не удалось удалить аккаунт", true);
  }
});

// Auth forms
ui.auth.registerForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const username = ui.auth.regUsername.value.trim();
  const password = ui.auth.regPassword.value.trim();
  const goldenKey = ui.auth.regGoldenKey.value.trim();
  if (!username || !password || !goldenKey) {
    toast("Заполните все поля.", true);
    return;
  }
  apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password, golden_key: goldenKey }),
  })
    .then((data) => {
      sessionStorage.setItem("adminToken", data.token);
      sessionStorage.setItem("adminUser", data.username);
      hideAuth();
      loadAll();
      startAutoRefresh();
      toast("Регистрация выполнена, вы вошли.");
    })
    .catch((err) => toast(err.message || "Не удалось зарегистрироваться", true));
});

ui.auth.loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const username = ui.auth.loginUsername.value.trim();
  const password = ui.auth.loginPassword.value.trim();
  apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  })
    .then((data) => {
      sessionStorage.setItem("adminToken", data.token);
      sessionStorage.setItem("adminUser", data.username);
      hideAuth();
      loadAll();
      startAutoRefresh();
      toast("Вход выполнен.");
    })
    .catch((err) => toast(err.message || "Не удалось войти", true));
});

const init = async () => {
  const savedKey = getAdminKey();
  if (!savedKey) {
    showAuth();
    return;
  }
  hideAuth();
  loadAll();
  startAutoRefresh();
};

init();

// Settings
document.getElementById("settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const key = document.getElementById("settingsGoldenKey").value.trim();
  if (!key) {
    toast("Введите золотой ключ.", true);
    return;
  }
  try {
    await apiFetch("/api/auth/golden-key", {
      method: "PUT",
      body: JSON.stringify({ golden_key: key }),
    });
    toast("Золотой ключ обновлён.");
  } catch (error) {
    toast(error.message || "Не удалось обновить ключ", true);
  }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch (error) {
    // ignore
  }
  sessionStorage.removeItem("adminToken");
  sessionStorage.removeItem("adminUser");
  showAuth();
});




