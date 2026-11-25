"""Govee Bulb Controller — drive William's Giant LED Bulbs (H6008) via the official Govee Developer API.

No Govee app, no ads. Full control: on/off, brightness, RGB color, color temp,
plus a custom timed chase across bulbs.
"""
import os
import time
import json
import socket
import traceback
import threading
import requests
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

API_BASE = "https://developer-api.govee.com"
VERSION = "1.0.0"
BUILD_DATE = "2026-11-15"


def _load_key():
    k = os.environ.get("GOVEE_API_KEY", "")
    if k:
        return k
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(cfg) as f:
            return json.load(f).get("api_key", "")
    except Exception:
        return ""


API_KEY = _load_key()

# ---- error handlers (registered immediately after Flask()) ----
@app.errorhandler(400)
def e400(e): return jsonify(error="bad request", detail=str(e)), 400
@app.errorhandler(401)
def e401(e): return jsonify(error="unauthorized"), 401
@app.errorhandler(403)
def e403(e): return jsonify(error="forbidden — check GOVEE_API_KEY"), 403
@app.errorhandler(404)
def e404(e): return jsonify(error="not found"), 404
@app.errorhandler(405)
def e405(e): return jsonify(error="method not allowed"), 405
@app.errorhandler(413)
def e413(e): return jsonify(error="payload too large"), 413
@app.errorhandler(429)
def e429(e): return jsonify(error="rate limited — slow down"), 429
@app.errorhandler(500)
def e500(e): return jsonify(error="internal server error"), 500
@app.errorhandler(Exception)
def eany(e):
    traceback.print_exc()
    return jsonify(error="server error", detail=str(e)), 500


# ---- Govee API client ----
def _hdr():
    return {"Govee-API-Key": API_KEY, "Content-Type": "application/json"}


def list_devices():
    r = requests.get(f"{API_BASE}/v1/devices", headers=_hdr(), timeout=15)
    r.raise_for_status()
    return r.json()


def control(device, model, cmd):
    body = {"device": device, "model": model, "cmd": cmd}
    r = requests.put(f"{API_BASE}/v1/devices/control", headers=_hdr(), json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def get_state(device, model):
    r = requests.get(f"{API_BASE}/v1/devices/state",
                     params={"device": device, "model": model}, headers=_hdr(), timeout=15)
    r.raise_for_status()
    return r.json()


# ---- LAN control (UDP port 4003) — bypasses the cloud 10/min/bulb rate limit ----
LAN_PORT = 4003


def _load_lan_map():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lan_devices.json")
    try:
        with open(p) as f:
            return json.load(f)  # {device_id: ip}
    except Exception:
        return {}


LAN_MAP = _load_lan_map()


def lan_control(ip, cmd, data):
    """Fire-and-forget UDP command to a bulb's LAN API (no ACK, no rate limit)."""
    msg = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(msg, (ip, LAN_PORT))
    s.close()


def lan_color(ip, rgb):
    lan_control(ip, "colorwc", {"color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}, "colorTemInKelvin": 0})


def lan_turn(ip, on):
    lan_control(ip, "turn", {"value": 1 if on else 0})


def lan_brightness(ip, pct):
    lan_control(ip, "brightness", {"value": int(pct)})


# ---- LAN chase (fast, no rate limit) ----
_lan_chase_thread = None
_lan_chase_stop = threading.Event()


def _run_lan_chase(ip_list, colors, step_ms):
    """Theater 'chasing lights': one bright bulb runs along the string, showing a
    different color each step; each full loop the color sequence rotates by one so
    the pattern is never identical two laps in a row."""
    n = len(ip_list)
    ncolors = len(colors)
    for ip in ip_list:
        lan_turn(ip, False)          # start all-dark
    lap = 0
    while not _lan_chase_stop.is_set():
        for idx in range(n):
            if _lan_chase_stop.is_set():
                break
            prev = ip_list[(idx - 1) % n]
            cur = ip_list[idx]
            lan_turn(prev, False)
            lan_color(cur, colors[(idx + lap) % ncolors])
            lan_turn(cur, True)
            _lan_chase_stop.wait(step_ms / 1000.0)
        lap += 1


# ---- chase engine (timed color sequence across bulbs) ----
_chase_thread = None
_chase_stop = threading.Event()


def _run_chase(devices, colors, step_ms):
    """devices: list of {device, model}; colors: list of [r,g,b]; step_ms: per-step delay.
    Each bulb advances one color every step_ms, offset per bulb to form a wave."""
    n = len(devices)
    idx = 0
    while not _chase_stop.is_set():
        for i, dev in enumerate(devices):
            c = colors[(idx + i) % len(colors)]
            try:
                control(dev["device"], dev["model"], {"name": "color", "value": {"r": c[0], "g": c[1], "b": c[2]}})
            except Exception:
                pass
        idx += 1
        _chase_stop.wait(step_ms / 1000.0)


# ---- routes ----
@app.route("/ping")
def ping():
    return jsonify(ping="pong", app="govee-controller", version=VERSION)


@app.route("/version")
def version():
    return jsonify(
        version=VERSION,
        commit="n/a",
        build_date=BUILD_DATE,
        features=["device list", "on/off", "brightness", "RGB color", "color temp", "custom chase"],
    )


@app.route("/api/devices")
def api_devices():
    if not API_KEY:
        return jsonify(error="GOVEE_API_KEY not set"), 400
    data = list_devices()
    return jsonify(data)


@app.route("/api/control", methods=["POST"])
def api_control():
    if not API_KEY:
        return jsonify(error="GOVEE_API_KEY not set"), 400
    body = request.get_json(force=True)
    dev = body["device"]
    model = body["model"]
    cmd = body["cmd"]
    return jsonify(control(dev, model, cmd))


@app.route("/api/state")
def api_state():
    if not API_KEY:
        return jsonify(error="GOVEE_API_KEY not set"), 400
    dev = request.args.get("device")
    model = request.args.get("model")
    return jsonify(get_state(dev, model))


@app.route("/api/chase/start", methods=["POST"])
def api_chase_start():
    global _chase_thread
    if not API_KEY:
        return jsonify(error="GOVEE_API_KEY not set"), 400
    body = request.get_json(force=True)
    devices = body["devices"]       # [{device, model}]
    colors = body["colors"]         # [[r,g,b], ...]
    step_ms = int(body.get("step_ms", 1000))
    _chase_stop.clear()
    _chase_thread = threading.Thread(target=_run_chase, args=(devices, colors, step_ms), daemon=True)
    _chase_thread.start()
    return jsonify(started=True, devices=len(devices), colors=len(colors), step_ms=step_ms)


@app.route("/api/chase/stop", methods=["POST"])
def api_chase_stop():
    _chase_stop.set()
    return jsonify(stopped=True)


@app.route("/api/lan/devices")
def api_lan_devices():
    return jsonify(LAN_MAP)


@app.route("/api/lan/control", methods=["POST"])
def api_lan_control():
    body = request.get_json(force=True)
    ip = body["ip"]
    cmd = body["cmd"]          # {"name": "color", "value": {...}} OR {"name":"turn","value":1}
    name = cmd["name"]
    val = cmd["value"]
    if name == "color":
        lan_color(ip, (val["r"], val["g"], val["b"]))
    elif name == "turn":
        lan_turn(ip, bool(val))
    elif name == "brightness":
        lan_brightness(ip, val)
    return jsonify(ok=True)


@app.route("/api/lan/chase/start", methods=["POST"])
def api_lan_chase_start():
    global _lan_chase_thread
    body = request.get_json(force=True)
    ips = body["ips"]              # ["192.168.1.x", ...]
    colors = body["colors"]        # [[r,g,b], ...]
    step_ms = int(body.get("step_ms", 500))
    _lan_chase_stop.clear()
    _lan_chase_thread = threading.Thread(target=_run_lan_chase, args=(ips, colors, step_ms), daemon=True)
    _lan_chase_thread.start()
    return jsonify(started=True, ips=len(ips), colors=len(colors), step_ms=step_ms)


@app.route("/api/lan/chase/stop", methods=["POST"])
def api_lan_chase_stop():
    _lan_chase_stop.set()
    return jsonify(stopped=True)


# ---- visual layout dashboard (drag & drop) ----
def _load_json(name, default):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default


LAYOUT = _load_json("layout.json", {})
NAMES = _load_json("names.json", {})


def refresh_names():
    global NAMES
    try:
        data = list_devices()
        for d in data["data"]["devices"]:
            NAMES[d["device"]] = d["deviceName"]
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "names.json"), "w") as f:
            json.dump(NAMES, f, indent=2)
    except Exception:
        pass


@app.route("/api/layout", methods=["GET"])
def api_layout_get():
    if not NAMES:
        refresh_names()
    bulbs = []
    for device_id, ip in LAN_MAP.items():
        pos = LAYOUT.get(device_id, {})
        bulbs.append({"id": device_id, "name": NAMES.get(device_id, device_id),
                      "ip": ip, "x": pos.get("x", 0.5), "y": pos.get("y", 0.5)})
    return jsonify({"bulbs": bulbs})


@app.route("/api/layout", methods=["POST"])
def api_layout_save():
    global LAYOUT
    LAYOUT = request.get_json(force=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "layout.json"), "w") as f:
        json.dump(LAYOUT, f, indent=2)
    return jsonify(saved=True, count=len(LAYOUT))


@app.route("/layout")
def layout_page():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layout.html")
    try:
        with open(p) as f:
            return f.read()
    except Exception:
        return "<h1>layout.html missing</h1>"


# ---- chase presets ----
DEFAULT_PRESETS = {
    "Christmas": {"colors": [[0, 200, 0], [255, 0, 0], [0, 70, 255], [140, 0, 220],
                             [255, 200, 0], [255, 255, 255], [255, 80, 180]], "step_ms": 350},
    "Classic Red/Green": {"colors": [[255, 0, 0], [0, 200, 0]], "step_ms": 400},
    "All White": {"colors": [[255, 255, 255]], "step_ms": 400},
    "Red White Blue": {"colors": [[255, 0, 0], [255, 255, 255], [0, 70, 255]], "step_ms": 350},
    "Candy": {"colors": [[255, 80, 180], [0, 200, 0], [255, 255, 255], [255, 0, 0]], "step_ms": 350},
}
PRESETS = _load_json("presets.json", DEFAULT_PRESETS)


@app.route("/api/presets")
def api_presets():
    return jsonify(PRESETS)


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Govee Controller</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:radial-gradient(1200px 800px at 20% -10%, #1a2440 0%, #0b0f1a 55%, #05070d 100%); color:#e8ecf5; min-height:100vh; }
  header { padding:28px 32px 8px; }
  h1 { margin:0; font-size:26px; font-weight:700; letter-spacing:-.3px; }
  .sub { color:#8b95b0; font-size:13px; margin-top:4px; }
  main { padding:20px 32px 40px; display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }
  .card { background:rgba(255,255,255,.045); border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:18px;
          backdrop-filter:blur(14px); box-shadow:0 8px 30px rgba(0,0,0,.35); }
  .card h2 { margin:0 0 6px; font-size:16px; }
  .mac { color:#8b95b0; font-size:11px; font-family:monospace; margin-bottom:12px; }
  .row { display:flex; align-items:center; gap:10px; margin:8px 0; }
  button { background:linear-gradient(135deg,#3b5bdb,#7048e8); color:#fff; border:0; border-radius:10px; padding:9px 14px; font-size:13px; cursor:pointer; }
  button.off { background:linear-gradient(135deg,#5c6573,#39404d); }
  input[type=color] { width:42px; height:42px; border:0; border-radius:8px; background:none; cursor:pointer; }
  input[type=range] { flex:1; }
  .bar { display:flex; gap:8px; margin:14px 0 0; flex-wrap:wrap; }
  .chasepanel { grid-column:1 / -1; }
  .chasepanel .swatches { display:flex; gap:10px; margin:10px 0; }
  .sw { width:34px; height:34px; border-radius:50%; border:2px solid rgba(255,255,255,.25); cursor:pointer; }
</style></head>
<body>
<header><h1>Govee Controller</h1><div class="sub">Direct control · no app · no ads</div></header>
<main id="grid"></main>
<div class="chasepanel card" style="grid-column:1/-1">
  <h2>Chase</h2>
  <div class="row">Palette: <span id="palette" class="swatches"></span> <button onclick="addSwatch()">+ color</button></div>
  <div class="row">Step: <input id="stepms" type="range" min="200" max="5000" step="100" value="1000"> <span id="steplbl">1000ms</span></div>
  <div class="bar"><button id="chaseBtn" onclick="toggleChase()">Start chase</button> <button class="off" onclick="stopChase()">Stop</button></div>
</div>
<script>
let devices = [];
let chaseColors = [[255,0,0],[0,255,0],[0,0,255]];
let chasing = false;

function hex(rgb){ return '#'+rgb.map(c=>c.toString(16).padStart(2,'0')).join(''); }

async function load(){
  const r = await fetch('/api/devices'); const d = await r.json();
  devices = (d.data && d.data.devices) ? d.data.devices.filter(x=>x.controllable) : [];
  document.getElementById('grid').innerHTML = devices.map((dev,i)=>`
    <div class="card">
      <h2>${dev.deviceName || ('Bulb '+(i+1))}</h2>
      <div class="mac">${dev.model} · ${dev.device}</div>
      <div class="row">
        <input type="color" value="#ffffff" oninput="setColor(${i},this.value)">
        <button onclick="toggle(${i})">On/Off</button>
        <button class="off" onclick="setBright(${i},100)">100%</button>
      </div>
      <div class="row"><input type="range" min="1" max="100" value="100" onchange="setBright(${i},this.value)"></div>
    </div>`).join('');
}

function post(url, body){ return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json()); }

function toggle(i){ const d=devices[i]; post('/api/control',{device:d.device,model:d.model,cmd:{name:'turn',value:'off'}}); setTimeout(()=>post('/api/control',{device:d.device,model:d.model,cmd:{name:'turn',value:'on'}}),120); }

function setColor(i, hexval){
  const c=[parseInt(hexval.slice(1,3),16),parseInt(hexval.slice(3,5),16),parseInt(hexval.slice(5,7),16)];
  const d=devices[i];
  post('/api/control',{device:d.device,model:d.model,cmd:{name:'color',value:{r:c[0],g:c[1],b:c[2]}}});
}

function setBright(i, v){ const d=devices[i]; post('/api/control',{device:d.device,model:d.model,cmd:{name:'brightness',value:parseInt(v)}}); }

function renderPalette(){ document.getElementById('palette').innerHTML = chaseColors.map((c,idx)=>`<div class="sw" style="background:${hex(c)}" onclick="chaseColors.splice(${idx},1);renderPalette()"></div>`).join(''); }
function addSwatch(){ const c=[Math.floor(Math.random()*255),Math.floor(Math.random()*255),Math.floor(Math.random()*255)]; chaseColors.push(c); renderPalette(); }

async function toggleChase(){
  const step=parseInt(document.getElementById('stepms').value);
  if(!chasing){ await post('/api/chase/start',{devices:devices.map(d=>({device:d.device,model:d.model})),colors:chaseColors,step_ms:step}); document.getElementById('chaseBtn').textContent='Chasing…'; chasing=true; }
  else { stopChase(); }
}
async function stopChase(){ await post('/api/chase/stop',{}); document.getElementById('chaseBtn').textContent='Start chase'; chasing=false; }

document.getElementById('stepms').oninput=function(){ document.getElementById('steplbl').textContent=this.value+'ms'; };
renderPalette(); load();
</script>
</body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8813)), debug=False)
