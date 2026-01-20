import express from "express";
import SteamUser from "steam-user";
import SteamTotp from "steam-totp";

const {
  STEAM_BRIDGE_USERNAME,
  STEAM_BRIDGE_PASSWORD,
  STEAM_BRIDGE_SHARED_SECRET,
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
  const rpRaw = user.rich_presence || {};
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
  const in_match =
    data.appid === 570 ? isInDotaMatch(rp) || isInDotaMatchRaw(rpRaw) : false;
  const status =
    rp.status ||
    rp.steam_display ||
    (rp.lobby ? rp.lobby : rpRaw.find((e) => e.key === "lobby")?.value || "") ||
    (data.in_game ? "in_game" : "offline");
  res.json({
    presence_state: data.in_game ? "in_game" : "not_in_game",
    presence_display: data.appid || "",
    presence_in_match: in_match,
    persona_state: data.persona_state,
    appid: data.appid,
    steamid64: data.steamid64,
    presence_status: status,
    lobby_info: rp.lobby || rpRaw.find((e) => e.key === "lobby")?.value || "",
  });
});

const port = process.env.PORT || 4000;
app.listen(port, () => console.log(`[bridge] listening on ${port}`));

