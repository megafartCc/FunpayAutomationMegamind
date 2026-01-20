import express from 'express';
import SteamUser from 'steam-user';
import SteamTotp from 'steam-totp';

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

client.on('loggedOn', () => {
  loggedOn = true;
  console.log('[bridge] Logged into Steam');
  client.setPersona(SteamUser.EPersonaState.Online);
});

client.on('error', (err) => {
  loggedOn = false;
  console.error('[bridge] Steam error', err);
});

client.on('disconnected', () => {
  loggedOn = false;
  console.warn('[bridge] Steam disconnected');
});

client.on('friendsList', () => {
  for (const steamid of Object.keys(client.myFriends || {})) {
    client.getPersonas([steamid]);
  }
});

client.on('user', (sid, user) => {
  const id64 = sid.getSteamID64();
  presence.set(id64, {
    steamid64: id64,
    persona_state: user.persona_state,
    appid: user.gameid || null,
    in_game: !!user.gameid,
    rich_presence: user.rich_presence || {},
    last_updated: Date.now(),
  });
});

function logOn() {
  if (!STEAM_BRIDGE_USERNAME || !STEAM_BRIDGE_PASSWORD) {
    console.error('[bridge] Missing STEAM_BRIDGE_USERNAME/STEAM_BRIDGE_PASSWORD');
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

app.get('/health', (_req, res) => {
  res.json({ status: loggedOn ? 'ok' : 'down', loggedOn });
});

app.get('/presence/:steamid', (req, res) => {
  const sid = req.params.steamid;
  const data = presence.get(sid);
  if (!data) return res.status(404).json({ error: 'not_found' });
  res.json({
    presence_state: data.in_game ? 'in_game' : 'not_in_game',
    presence_display: data.appid || '',
    presence_in_match: false,
    persona_state: data.persona_state,
    appid: data.appid,
    steamid64: data.steamid64,
  });
});

const port = process.env.PORT || 4000;
app.listen(port, () => console.log(`[bridge] listening on ${port}`));

