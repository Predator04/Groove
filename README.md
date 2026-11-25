# 💡 Groove

A self-hosted web controller for Govee "Giant LED" bulbs (H6008 and other
Wi-Fi+BLE models). No app, no ads, no cloud rate limit — just your bulbs,
your network, your rules.

## Why

Govee's official API caps you at **10 commands/min per bulb**, which makes
fast synchronized effects impossible. Groove talks to your bulbs directly
over the LAN (UDP port 4003) — **zero rate limit** — and gives you effects
the Govee app can't do.

## Features

- **24 effects**: Chase, Wave, Twinkle, Meteor, Breathe, Fire, Strobe, Gradient,
  Solid, Sparkle, Heartbeat, Lightning, Police, Rainbow, Countdown, SOS, Ocean,
  Candy Cane, Jack-o-Lantern, Fireworks, Disco, Aurora, Sunset, Movie
- **Drag & drop layout** — arrange your bulbs on a canvas to match your real
  setup; the chase follows the left-to-right order
- **Presets** — Christmas, Classic Red/Green, All White, Red White Blue, Candy
- **Per-bulb control** — click any bulb to set color, brightness, on/off
- **Scheduler** — run any effect at a set time, daily recurring (persists)
- **Dusk-to-dawn** — auto on at sunset, off at sunrise (enter your ZIP code)
- **Scenes** — save/recall whole color layouts; each scene gets a trigger URL (Siri/Stream Deck)
- **Zero rate limit** — raw UDP control, no cloud throttle

## Setup (under a minute)

1. Install Python 3 and `pip install -r requirements.txt`
2. Run `python app.py` → open **http://localhost:8813/setup**
3. Paste your **Govee API key** (Govee Home app → Profile → About → Apply for API Key — it's emailed to you)
4. In the Govee Home app, open each bulb → ⚙️ → **LAN Control** → on
5. Click **Scan for bulbs**, then **Save & open dashboard**

That's it. The setup page writes `config.json` (key) and `lan_devices.json`
(bulb → IP) for you — no manual file editing.

## The dashboard

Open **http://localhost:8813/layout**:

- **Drag bulbs** to match your physical layout (auto-saves)
- Pick an **effect** + **preset**, set speed, hit **Start**
- Click a bulb for color / brightness / power

## Requirements

- Machine on the **same Wi-Fi** as the bulbs (multicast/broadcast must be allowed)
- Govee bulbs with **LAN Control enabled** (per device)
- Govee API key (for device names + fallback cloud control)

## Endpoints

- `GET /api/devices` · `POST /api/control` · `GET /api/state` — cloud API
- `POST /api/effect/start` `{ips, effect, colors, step_ms}` · `POST /api/effect/stop` — LAN effects
- `GET /api/scan` — LAN discovery
- `POST /api/setup` `{api_key, devices}` — one-shot onboarding
- `GET /api/presets` · `GET /api/layout` · `POST /api/layout` — presets + saved arrangement
- `POST /api/lan/control` — instant per-bulb UDP control
- `GET /api/update` — checks GitHub for a newer version (shows an in-app banner)

## LAN protocol (reference)

- Discovery: UDP multicast `239.255.255.250:4001` → devices reply on `4002`
- Control: UDP unicast to `device-ip:4003` (fire-and-forget):
  - `{"msg":{"cmd":"turn","data":{"value":0|1}}}`
  - `{"msg":{"cmd":"brightness","data":{"value":1-100}}}`
  - `{"msg":{"cmd":"colorwc","data":{"color":{"r","g","b"},"colorTemInKelvin":0}}}`
