const ui = {
  health: document.getElementById("healthStatus"),
  total: document.getElementById("statTotal"),
  active: document.getElementById("statActive"),
  available: document.getElementById("statAvailable"),
  recent: document.getElementById("statRecent"),
  activeTable: document.getElementById("activeRentals"),
  inventoryTable: document.getElementById("inventoryTable"),
  notifications: document.getElementById("notificationsList"),
  adminKey: document.getElementById("adminKey"),
  saveKey: document.getElementById("saveKey"),
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
    maFile: document.getElementById("manageMaFile"),
    maFileJson: document.getElementById("manageMaFileJson"),
    duration: document.getElementById("manageDuration"),
    owner: document.getElementById("manageOwner"),
    start: document.getElementById("manageStart"),
    update: document.getElementById("updateAccount"),
    assign: document.getElementById("assignAccount"),
    release: document.getElementById("releaseAccount"),
    extend: document.getElementById("extendAccount"),
    extendHours: document.getElementById("extendHours"),
    extendOwner: document.getElementById("extendOwner"),
    extendOwnerHours: document.getElementById("extendOwnerHours"),
    delete: document.getElementById("deleteAccount"),
  },
  addForm: document.getElementById("addAccountForm"),
  addStatus: document.getElementById("addStatus"),
};

let accountsCache = [];
let selectedId = null;
let chatsCache = [];
let selectedChatId = null;

const toast = (message, isError = false) => {
  ui.toast.textContent = message;
  ui.toast.style.borderColor = isError ? "rgba(242, 95, 92, 0.6)" : "rgba(242, 176, 90, 0.4)";
  ui.toast.classList.add("show");
  setTimeout(() => ui.toast.classList.remove("show"), 2800);
};

const getAdminKey = () => sessionStorage.getItem("adminKey") || "";

const apiFetch = async (path, options = {}) => {
  const headers = options.headers ? { ...options.headers } : {};
  headers["Content-Type"] = "application/json";
  const adminKey = getAdminKey();
  if (adminKey) {
    headers["X-Admin-Key"] = adminKey;
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Request failed");
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
    ui.manage.maFile.value = "";
    ui.manage.maFileJson.value = "";
    ui.manage.duration.value = "";
    ui.manage.owner.value = "";
    ui.manage.start.value = "";
    return;
  }

  ui.manage.id.value = account.id;
  ui.manage.name.value = account.account_name || "";
  ui.manage.login.value = account.login || "";
  ui.manage.password.value = account.password || "";
  ui.manage.maFile.value = account.path_to_maFile || "";
  ui.manage.maFileJson.value = "";
  ui.manage.duration.value = account.rental_duration || "";
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
    ui.health.textContent = "FunPay ready";
  } else if (status?.funpay_enabled) {
    ui.health.textContent = "FunPay starting";
  } else {
    ui.health.textContent = "FunPay disabled";
  }
};

const renderActiveRentals = (items) => {
  if (!items.length) {
    ui.activeTable.innerHTML = "<tr><td colspan=\"6\">No active rentals.</td></tr>";
    return;
  }
  ui.activeTable.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.id}</td>
          <td>${item.account_name}</td>
          <td>${item.owner}</td>
          <td>${item.login}</td>
          <td>${formatDate(item.rental_start)}</td>
          <td>${item.rental_duration}</td>
        </tr>
      `
    )
    .join("");
};

const renderInventory = (items) => {
  const query = ui.search.value.trim().toLowerCase();
  const filtered = items.filter((item) => {
    const name = item.account_name?.toLowerCase() || "";
    const owner = item.owner?.toLowerCase() || "";
    return !query || name.includes(query) || owner.includes(query);
  });

  if (!filtered.length) {
    ui.inventoryTable.innerHTML = "<tr><td colspan=\"6\">No accounts found.</td></tr>";
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
          <td>${showPasswords ? item.password : "??????"}</td>
          <td>${item.owner || "-"}</td>
          <td>${item.rental_duration}</td>
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

const renderNotifications = (items) => {
  if (!items.length) {
    ui.notifications.innerHTML = "<div class=\"notice\"><h4>No notifications</h4><p>System events will appear here.</p></div>";
    return;
  }
  ui.notifications.innerHTML = items
    .map(
      (item) => `
        <div class="notice">
          <h4>${item.level?.toUpperCase() || "INFO"} - ${formatDate(item.created_at)}</h4>
          <p>${escapeHtml(item.message)}</p>
          <p>Owner: ${item.owner || "-"} | Account: ${item.account_id || "-"}</p>
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
    ui.chats.list.innerHTML = "<div class=\"notice\"><h4>No chats</h4><p>No chats found.</p></div>";
    return;
  }

  ui.chats.list.innerHTML = filtered
    .map(
      (chat) => `
        <button class="chat-item ${chat.id === selectedChatId ? "active" : ""}" data-id="${chat.id}">
          <div>
            <h4>${escapeHtml(chat.name || "Unknown")}</h4>
            <p>${escapeHtml(chat.last_message_text || "")}</p>
          </div>
          ${chat.unread ? '<span class="badge">new</span>' : ''}
        </button>
      `
    )
    .join("");

  document.querySelectorAll(".chat-item").forEach((item) => {
    item.addEventListener("click", () => {
      selectedChatId = Number(item.dataset.id);
      const chat = chatsCache.find((c) => c.id === selectedChatId);
      ui.chats.title.textContent = chat?.name || "Chat";
      ui.chats.subtitle.textContent = `Chat ID: ${selectedChatId}`;
      ui.chats.list.querySelectorAll(".chat-item").forEach((row) => {
        row.classList.toggle("active", Number(row.dataset.id) === selectedChatId);
      });
      loadChatHistory();
    });
  });
};

const renderChatMessages = (items) => {
  if (!items.length) {
    ui.chats.messages.innerHTML = "<div class=\"notice\"><h4>No messages</h4><p>Select a chat to load history.</p></div>";
    return;
  }

  ui.chats.messages.innerHTML = items
    .map((message) => {
      const author = message.author || "Unknown";
      const text = escapeHtml(message.text || "");
      const image = message.image_link
        ? `<a href="${message.image_link}" target="_blank" rel="noreferrer">View image</a>`
        : "";
      const type = message.type ? `(${message.type})` : "";
      return `
        <div class="chat-message ${message.by_bot ? "self" : ""}">
          <h5>${escapeHtml(author)} ${type}</h5>
          <p>${text || "(no text)"}</p>
          ${image}
        </div>
      `;
    })
    .join("");
};

const loadChats = async () => {
  if (!getAdminKey()) {
    ui.chats.list.innerHTML = "<div class=\"notice\"><h4>Admin key needed</h4><p>Set the admin key to load chats.</p></div>";
    return;
  }
  try {
    const data = await apiFetch("/api/chats");
    chatsCache = data.items || [];
    renderChatList(chatsCache);
  } catch (error) {
    toast(error.message || "Failed to load chats", true);
  }
};

const loadChatHistory = async () => {
  if (!selectedChatId) {
    ui.chats.messages.innerHTML = "<div class=\"notice\"><h4>Select a chat</h4><p>Pick a chat to view messages.</p></div>";
    return;
  }
  try {
    const data = await apiFetch(`/api/chats/${selectedChatId}/history?limit=60`);
    renderChatMessages(data.items || []);
  } catch (error) {
    toast(error.message || "Failed to load history", true);
  }
};

const loadAll = async () => {
  try {
    const [health, stats, accounts, rentals, notices] = await Promise.all([
      apiFetch("/api/health"),
      apiFetch("/api/stats"),
      apiFetch("/api/accounts"),
      apiFetch("/api/rentals/active"),
      apiFetch("/api/notifications"),
    ]);

    renderHealth(health);
    renderStats(stats);
    accountsCache = accounts.items || [];
    renderInventory(accountsCache);
    renderActiveRentals(rentals.items || []);
    renderNotifications(notices.items || []);

    if (selectedId) {
      const selected = accountsCache.find((acc) => acc.id === selectedId);
      setManagePanel(selected || null);
    }

    loadChats();
  } catch (error) {
    toast(error.message || "Failed to load data", true);
  }
};

ui.saveKey.addEventListener("click", () => {
  sessionStorage.setItem("adminKey", ui.adminKey.value.trim());
  toast("Admin key saved.");
  loadChats();
});

ui.refreshAll.addEventListener("click", () => {
  loadAll();
});

ui.search.addEventListener("input", () => renderInventory(accountsCache));
ui.showPasswords.addEventListener("change", () => renderInventory(accountsCache));

ui.chats.search.addEventListener("input", () => renderChatList(chatsCache));
ui.chats.refresh.addEventListener("click", () => loadChats());
ui.chats.loadHistory.addEventListener("click", () => loadChatHistory());

ui.chats.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedChatId) {
    toast("Select a chat first.", true);
    return;
  }
  const text = ui.chats.input.value.trim();
  if (!text) {
    toast("Message is empty.", true);
    return;
  }
  try {
    await apiFetch(`/api/chats/${selectedChatId}/send`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    ui.chats.input.value = "";
    toast("Message sent.");
    loadChatHistory();
  } catch (error) {
    toast(error.message || "Send failed", true);
  }
});

ui.addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(ui.addForm);
  const payload = Object.fromEntries(formData.entries());
  payload.rental_duration = Number(payload.rental_duration || 0);
  if (!payload.path_to_maFile) {
    delete payload.path_to_maFile;
  }
  if (!payload.mafile_json) {
    delete payload.mafile_json;
  }
  if (!payload.owner) {
    delete payload.owner;
  }
  try {
    await apiFetch("/api/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    ui.addForm.reset();
    toast("Account added.");
    loadAll();
  } catch (error) {
    toast(error.message || "Failed to add account", true);
  }
});

ui.manage.update.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Select an account first.", true);
    return;
  }
  const payload = {
    account_name: ui.manage.name.value.trim(),
    login: ui.manage.login.value.trim(),
    password: ui.manage.password.value.trim(),
    path_to_maFile: ui.manage.maFile.value.trim(),
    mafile_json: ui.manage.maFileJson.value.trim(),
    rental_duration: Number(ui.manage.duration.value || 0),
  };
  if (!payload.path_to_maFile) {
    delete payload.path_to_maFile;
  }
  if (!payload.mafile_json) {
    delete payload.mafile_json;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    toast("Account updated.");
    loadAll();
  } catch (error) {
    toast(error.message || "Update failed", true);
  }
});

ui.manage.assign.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Select an account first.", true);
    return;
  }
  const owner = ui.manage.owner.value.trim();
  if (!owner) {
    toast("Owner is required.", true);
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}/assign`, {
      method: "POST",
      body: JSON.stringify({ owner }),
    });
    toast("Owner assigned.");
    loadAll();
  } catch (error) {
    toast(error.message || "Assign failed", true);
  }
});

ui.manage.extendOwner.addEventListener("click", async () => {
  const owner = ui.manage.owner.value.trim();
  if (!owner) {
    toast("Owner is required.", true);
    return;
  }
  const hours = Number(ui.manage.extendOwnerHours.value || 0);
  if (hours <= 0) {
    toast("Enter hours to extend.", true);
    return;
  }
  try {
    await apiFetch(`/api/rentals/user/${encodeURIComponent(owner)}/extend`, {
      method: "POST",
      body: JSON.stringify({ hours }),
    });
    toast("Owner rentals extended.");
    ui.manage.extendOwnerHours.value = "";
    loadAll();
  } catch (error) {
    toast(error.message || "Extend owner failed", true);
  }
});

ui.manage.release.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Select an account first.", true);
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}/release`, {
      method: "POST",
    });
    toast("Account released.");
    loadAll();
  } catch (error) {
    toast(error.message || "Release failed", true);
  }
});

ui.manage.extend.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Select an account first.", true);
    return;
  }
  const hours = Number(ui.manage.extendHours.value || 0);
  if (hours <= 0) {
    toast("Enter hours to extend.", true);
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}/extend`, {
      method: "POST",
      body: JSON.stringify({ hours }),
    });
    toast("Rental extended.");
    ui.manage.extendHours.value = "";
    loadAll();
  } catch (error) {
    toast(error.message || "Extend failed", true);
  }
});

ui.manage.delete.addEventListener("click", async () => {
  if (!selectedId) {
    toast("Select an account first.", true);
    return;
  }
  if (!confirm("Delete this account group?")) {
    return;
  }
  try {
    await apiFetch(`/api/accounts/${selectedId}`, {
      method: "DELETE",
    });
    toast("Account deleted.");
    selectedId = null;
    setManagePanel(null);
    loadAll();
  } catch (error) {
    toast(error.message || "Delete failed", true);
  }
});

const init = () => {
  const savedKey = getAdminKey();
  if (savedKey) {
    ui.adminKey.value = savedKey;
  }
  loadAll();
};

init();
