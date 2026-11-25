# Groove — Govee Bulb Controller

A no-ads, self-hosted controller for Govee "Giant LED" bulbs (H6008 and other
Wi-Fi+BLE models). Two control paths:

- **Cloud API** (`/api/*`) — official Govee Developer API. Simple but rate-limited
  to 10 commands/min per bulb.
- **LAN UDP** (`/api/lan/*`) — direct UDP control on port 4003. **No rate limit**,
  so it can drive fast synchronized chases across all bulbs.

## Setup

1. `pip install -r requirements.txt`
2. Copy `config.example.json` → `config.json` and put your Govee API key in it
   (Govee Home app → Profile → About → Apply for API Key; it's emailed to you).
3. Enable **LAN Control** on each bulb (Govee Home → tap device → gear → LAN Control → on).
4. Discover bulb IPs: run `scripts/govee_scan2.py` (must run on a host on the same
   LAN, e.g. Windows) and put the `device → ip` pairs into `lan_devices.json`.
5. `python app.py` (serves on port 8813).

## Endpoints

- `GET /api/devices` — list devices (cloud)
- `POST /api/control` — cloud on/off/brightness/color/temp
- `GET /api/state` — cloud device state
- `GET /api/lan/devices` — device → IP map
- `POST /api/lan/control` — instant UDP on/off/brightness/color
- `POST /api/lan/chase/start` — fast synchronized chase (body: `{"ips":[...],"colors":[[r,g,b],...],"step_ms":N}`)
- `POST /api/lan/chase/stop`
- `GET /` — glass dashboard

## LAN protocol notes

- Discovery: UDP multicast `239.255.255.250:4001` (devices reply on `4002`).
- Control: UDP unicast to `device-ip:4003`, fire-and-forget JSON:
  - turn: `{"msg":{"cmd":"turn","data":{"value":0|1}}}`
  - brightness: `{"msg":{"cmd":"brightness","data":{"value":1-100}}}`
  - color: `{"msg":{"cmd":"colorwc","data":{"color":{"r","g","b"},"colorTemInKelvin":0}}}`
- Control commands get no ACK — don't block on a reply.
