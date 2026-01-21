import express from "express";
import SteamUser from "steam-user";
import SteamTotp from "steam-totp";

const {
  STEAM_BRIDGE_USERNAME,
  STEAM_BRIDGE_PASSWORD,
  STEAM_BRIDGE_SHARED_SECRET,
  PRESENCE_DEBUG_TOKEN,
} = process.env;

const app = express();
app.use(express.json());

const client = new SteamUser();
const presence = new Map();
let loggedOn = false;

client.on("loggedOn", () => {
  loggedOn = true;
  console.log("[bridge] Logged into Steam");
  client.setPersona(SteamUser.EPersonaState.Online);
});

client.on("error", (err) => {
  loggedOn = false;
  console.error("[bridge] Steam error", err);
});

client.on("disconnected", () => {
  loggedOn = false;
  console.warn("[bridge] Steam disconnected");
});

client.on("friendsList", () => {
  for (const steamid of Object.keys(client.myFriends || {})) {
    client.getPersonas([steamid]);
  }
});

// Periodically refresh personas so presence stays current
setInterval(() => {
  if (!loggedOn) return;
  const ids = Object.keys(client.myFriends || {});
  if (ids.length) {
    client.getPersonas(ids);
  }
}, 30000);

client.on("user", (sid, user) => {
  const id64 = sid.getSteamID64();
  const previous = presence.get(id64);
  let rpRaw = user.rich_presence || {};
  if (Array.isArray(rpRaw) && rpRaw.length === 0 && previous) {
    rpRaw = previous.rich_presence_raw || rpRaw;
  }
  const rp = Array.isArray(rpRaw)
    ? Object.fromEntries(rpRaw.map((entry) => [entry.key, entry.value]))
    : rpRaw;
  if (user.gameid === "570" || user.gameid === 570) {
    console.log("[bridge] Dota RP", id64, rpRaw);
  }
  presence.set(id64, {
    steamid64: id64,
    persona_state: user.persona_state,
    appid: user.gameid || null,
    in_game: !!user.gameid,
    rich_presence: rp,
    rich_presence_raw: rpRaw,
    last_updated: Date.now(),
  });
});

function isInDotaMatch(rp) {
  if (!rp || typeof rp !== "object") return false;
  const status = String(rp.status || "").toLowerCase();
  const display = String(rp.steam_display || "").toLowerCase();
  const lobby = String(rp.lobby || "").toLowerCase();
  const hasLevel = rp.level !== undefined;
  const hasMatchId = rp.matchid !== undefined || rp.watchable_match_id !== undefined;
  const hasStateOrMode = rp.state !== undefined || rp.mode !== undefined;
  const hasLobbyId = rp.lobby_id !== undefined || rp.lobbyid !== undefined || lobby.length > 0;
  const lobbyStates = ["run", "serversetup"];
  const indicators = [
    "heroselection",
    "strategytime",
    "playing",
    "ranked",
    "turbo",
    "captains",
    "draft",
    "match",
    "private_lobby",
    "finding_match",
  ];
  const lobbyStateHit = lobbyStates.some((kw) => lobby.includes(`lobby_state: ${kw}`));
  return (
    hasLevel ||
    hasMatchId ||
    hasLobbyId ||
    hasStateOrMode ||
    lobbyStateHit ||
    indicators.some((kw) => display.includes(kw) || status.includes(kw))
  );
}

function isInDotaMatchRaw(raw) {
  if (!Array.isArray(raw)) return false;
  const lobbyEntry = raw.find((e) => (e.key || "").toLowerCase() === "lobby");
  if (lobbyEntry && typeof lobbyEntry.value === "string") {
    const lv = lobbyEntry.value.toLowerCase();
    if (lv.includes("lobby_state: run") || lv.includes("lobby_state: serversetup")) return true;
  }
  return false;
}

function toHeroDisplay(token) {
  if (!token) return "";
  const normalized = token.startsWith("#") ? token.slice(1) : token;
  if (!normalized.startsWith("npc_dota_hero_")) return normalized;
  const name = normalized.replace("npc_dota_hero_", "").replace(/_/g, " ");
  return name.replace(/\b\w/g, (c) => c.toUpperCase());
}

function normalizeKey(key) {
  return String(key || "").toLowerCase();
}

function getRichPresenceValue(rp, rpRaw, key) {
  const target = normalizeKey(key);
  if (rp && typeof rp === "object") {
    for (const [k, v] of Object.entries(rp)) {
      if (normalizeKey(k) === target) return v;
    }
  }
  if (Array.isArray(rpRaw)) {
    const entry = rpRaw.find((e) => normalizeKey(e.key) === target);
    if (entry) return entry.value;
  }
  return undefined;
}

function parseIntMaybe(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number" && Number.isFinite(value)) return Math.floor(value);
  const raw = String(value).trim();
  if (!raw) return null;
  const parsed = Number.parseInt(raw, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function extractHeroToken(rp, rpRaw) {
  const candidates = [
    rp?.param2,
    rp?.hero,
    rp?.hero_name,
    rp?.heroname,
    rp?.npc_dota_hero,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  if (Array.isArray(rpRaw)) {
    const entry = rpRaw.find((e) => (e.key || "").toLowerCase() === "param2");
    if (entry && typeof entry.value === "string" && entry.value.trim()) {
      return entry.value.trim();
    }
  }
  return "";
}

function extractHeroLevel(rp, rpRaw) {
  const raw = getRichPresenceValue(rp, rpRaw, "level");
  const level = parseIntMaybe(raw);
  return Number.isFinite(level) && level >= 0 ? level : null;
}

function extractMatchSeconds(rp, rpRaw) {
  const nowSec = Math.floor(Date.now() / 1000);
  const keys = [
    "matchtime",
    "match_time",
    "game_time",
    "gametime",
    "elapsed",
    "elapsed_time",
    "match_duration",
    "duration",
    "time",
    "start_time",
    "starttime",
  ];

  for (const key of keys) {
    const raw = getRichPresenceValue(rp, rpRaw, key);
    const value = parseIntMaybe(raw);
    if (value === null) continue;

    if (key.includes("start")) {
      let start = value;
      if (start > 1e12) start = Math.floor(start / 1000);
      const elapsed = nowSec - start;
      if (elapsed > 0 && elapsed < 12 * 60 * 60) return elapsed;
      continue;
    }

    let seconds = value;
    if (seconds > 1e12) seconds = Math.floor(seconds / 1000);
    if (seconds > 12 * 60 * 60 && seconds < nowSec) {
      const elapsed = nowSec - seconds;
      if (elapsed > 0 && elapsed < 12 * 60 * 60) return elapsed;
    }
    if (seconds >= 0 && seconds < 12 * 60 * 60) return seconds;
  }

  return null;
}

function formatMatchTime(seconds) {
  if (seconds === null || seconds === undefined) return null;
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function logOn() {
  if (!STEAM_BRIDGE_USERNAME || !STEAM_BRIDGE_PASSWORD) {
    console.error("[bridge] Missing STEAM_BRIDGE_USERNAME/STEAM_BRIDGE_PASSWORD");
    return;
  }
  const details = {
    accountName: STEAM_BRIDGE_USERNAME,
    password: STEAM_BRIDGE_PASSWORD,
  };
  if (STEAM_BRIDGE_SHARED_SECRET) {
    details.twoFactorCode = SteamTotp.getAuthCode(STEAM_BRIDGE_SHARED_SECRET);
  }
  client.logOn(details);
}

logOn();

app.get("/health", (_req, res) => {
  res.json({ status: loggedOn ? "ok" : "down", loggedOn });
});

app.get("/presence/:steamid", (req, res) => {
  const sid = req.params.steamid;
  const data = presence.get(sid);
  if (!data) return res.status(404).json({ error: "not_found" });
  const rp = data.rich_presence || {};
  const rpRaw = data.rich_presence_raw || [];
  const lobbyRaw =
    rp.lobby ||
    (Array.isArray(rpRaw)
      ? rpRaw.find((e) => (e.key || "").toLowerCase() === "lobby")?.value || ""
      : "");
  const lobbyLower = String(lobbyRaw || "").toLowerCase();
  const lobbyStateHit = /lobby_state:\s*(run|serversetup)/.test(lobbyLower);
  const statusLower = String(rp.status || "").toLowerCase();
  const displayLower = String(rp.steam_display || "").toLowerCase();
  const statusKeywords = ["private_lobby", "finding_match", "playing", "match", "ranked", "turbo"];
  const statusHit = statusKeywords.some(
    (kw) => statusLower.includes(kw) || displayLower.includes(kw)
  );
  const in_match = isInDotaMatch(rp) || isInDotaMatchRaw(rpRaw) || lobbyStateHit || statusHit;
  const in_game = !!(data.in_game || data.appid || lobbyRaw || statusHit);
  const heroToken = extractHeroToken(rp, rpRaw);
  const heroName = toHeroDisplay(heroToken);
  const heroLevel = extractHeroLevel(rp, rpRaw);
  const matchSeconds = extractMatchSeconds(rp, rpRaw);
  const matchTime = formatMatchTime(matchSeconds);
  res.json({
    in_game,
    in_match,
    lobby_info: lobbyRaw || "",
    hero_token: heroToken || null,
    hero_name: heroName || null,
    hero_level: heroLevel ?? null,
    match_seconds: matchSeconds ?? null,
    match_time: matchTime ?? null,
  });
});

app.get("/presencefull/:steamid", (req, res) => {
  if (PRESENCE_DEBUG_TOKEN && req.query.token !== PRESENCE_DEBUG_TOKEN) {
    return res.status(403).json({ error: "forbidden" });
  }
  const sid = req.params.steamid;
  const data = presence.get(sid);
  if (!data) return res.status(404).json({ error: "not_found" });

  const rp = data.rich_presence || {};
  const rpRaw = data.rich_presence_raw || [];
  const heroToken = extractHeroToken(rp, rpRaw);
  const heroName = toHeroDisplay(heroToken);
  const heroLevel = extractHeroLevel(rp, rpRaw);
  const matchSeconds = extractMatchSeconds(rp, rpRaw);
  const matchTime = formatMatchTime(matchSeconds);

  res.json({
    ...data,
    derived: {
      hero_token: heroToken || null,
      hero_name: heroName || null,
      hero_level: heroLevel ?? null,
      match_seconds: matchSeconds ?? null,
      match_time: matchTime ?? null,
    },
  });
});

const port = process.env.PORT || 4000;
app.listen(port, () => console.log(`[bridge] listening on ${port}`));
