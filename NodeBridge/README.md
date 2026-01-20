# Funpay Steam Bridge (node-steam-user)

Small Express service using node-steam-user to expose presence.

## Config
- STEAM_BRIDGE_USERNAME
- STEAM_BRIDGE_PASSWORD
- STEAM_BRIDGE_SHARED_SECRET (optional for 2FA)
- PORT (default 4000)

## Endpoints
- GET /health -> { status, loggedOn }
- GET /presence/:steamid -> { presence_state, presence_display, appid, persona_state, steamid64 }

## Run
`
npm install
npm start
`

Then set STEAM_BRIDGE_URL in the Python app to the bridge host (e.g. http://localhost:4000).

