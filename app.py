"""Govee Bulb Controller — drive William's Giant LED Bulbs (H6008) via the official Govee Developer API.

No Govee app, no ads. Full control: on/off, brightness, RGB color, color temp,
plus a custom timed chase across bulbs.
"""
import os
import time
import json
import socket
import random
import traceback
import threading
import requests
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

API_BASE = "https://developer-api.govee.com"
VERSION = "1.7.1"
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

# last-known LAN state per bulb ip — served by /api/current so the dashboard mirrors live colors
CURRENT = {}


def lan_control(ip, cmd, data):
    """Fire-and-forget UDP command to a bulb's LAN API (no ACK, no rate limit)."""
    msg = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(msg, (ip, LAN_PORT))
        s.close()
    except Exception:
        pass  # one bulb offline must not kill the whole effect


def lan_color(ip, rgb):
    s = CURRENT.setdefault(ip, {})
    s.update({"r": int(rgb[0]), "g": int(rgb[1]), "b": int(rgb[2])})
    lan_control(ip, "colorwc", {"color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}, "colorTemInKelvin": 0})


def lan_turn(ip, on):
    CURRENT.setdefault(ip, {})["on"] = bool(on)
    lan_control(ip, "turn", {"value": 1 if on else 0})


def lan_brightness(ip, pct):
    CURRENT.setdefault(ip, {})["brightness"] = int(pct)
    lan_control(ip, "brightness", {"value": int(pct)})


def _hsv(h, s=1.0, v=1.0):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return [int(r * 255), int(g * 255), int(b * 255)]


# ---- effects engine (LAN UDP, no rate limit) ----
_effect_thread = None
_effect_stop = threading.Event()


def _run_effect(ip_list, effect, colors, step_ms):
    """Run a lighting effect across the bulbs.
    effect: chase | wave | twinkle | meteor | breathe | fire | strobe | gradient | solid"""
    n = len(ip_list)
    nc = len(colors)

    if effect == "chase":
        for ip in ip_list: lan_turn(ip, False)
        lap = 0
        while not _effect_stop.is_set():
            for idx in range(n):
                if _effect_stop.is_set(): break
                lan_turn(ip_list[(idx - 1) % n], False)
                lan_color(ip_list[idx], colors[(idx + lap) % nc])
                lan_turn(ip_list[idx], True)
                _effect_stop.wait(step_ms / 1000.0)
            lap += 1

    elif effect == "wave":
        for ip in ip_list: lan_turn(ip, True)
        idx = 0
        while not _effect_stop.is_set():
            for i, ip in enumerate(ip_list):
                lan_color(ip, colors[(idx + i) % nc])
            idx += 1
            _effect_stop.wait(step_ms / 1000.0)

    elif effect == "twinkle":
        for ip in ip_list: lan_turn(ip, False)
        while not _effect_stop.is_set():
            i = random.randrange(n)
            lan_color(ip_list[i], random.choice(colors))
            lan_turn(ip_list[i], True)
            _effect_stop.wait(max(step_ms, 60) / 1000.0)
            lan_turn(ip_list[i], False)

    elif effect == "meteor":
        for ip in ip_list: lan_turn(ip, True)
        tail = min(3, n - 1)
        head = colors[0]
        idx = 0
        while not _effect_stop.is_set():
            for i, ip in enumerate(ip_list):
                dist = (i - idx) % n
                if dist == 0:
                    lan_color(ip, head); lan_brightness(ip, 100)
                elif dist <= tail:
                    lan_color(ip, head); lan_brightness(ip, max(5, 100 - dist * 30))
                else:
                    lan_brightness(ip, 5)
            idx = (idx + 1) % n
            _effect_stop.wait(step_ms / 1000.0)

    elif effect == "breathe":
        for ip in ip_list:
            lan_turn(ip, True); lan_color(ip, colors[0])
        while not _effect_stop.is_set():
            for b in range(10, 101, 10):
                if _effect_stop.is_set(): break
                for ip in ip_list: lan_brightness(ip, b)
                _effect_stop.wait(step_ms / 1000.0)
            for b in range(90, 0, -10):
                if _effect_stop.is_set(): break
                for ip in ip_list: lan_brightness(ip, b)
                _effect_stop.wait(step_ms / 1000.0)

    elif effect == "fire":
        warm = colors or [[255, 60, 0], [255, 120, 0], [255, 40, 10], [255, 150, 40], [200, 30, 0]]
        for ip in ip_list: lan_turn(ip, True)
        while not _effect_stop.is_set():
            for ip in ip_list:
                lan_color(ip, random.choice(warm))
                lan_brightness(ip, random.randint(40, 100))
            _effect_stop.wait(max(step_ms, 100) / 1000.0)

    elif effect == "strobe":
        on = False
        while not _effect_stop.is_set():
            on = not on
            for ip in ip_list:
                if on:
                    lan_color(ip, colors[0]); lan_turn(ip, True)
                else:
                    lan_turn(ip, False)
            _effect_stop.wait(step_ms / 1000.0)

    elif effect == "sparkle":
        for ip in ip_list:
            lan_turn(ip, True); lan_color(ip, colors[0]); lan_brightness(ip, 10)
        while not _effect_stop.is_set():
            i = random.randrange(n)
            lan_brightness(ip_list[i], 100)
            _effect_stop.wait(0.12)
            lan_brightness(ip_list[i], 10)
            _effect_stop.wait(max(step_ms, 100) / 1000.0)

    elif effect == "heartbeat":
        while not _effect_stop.is_set():
            for _ in range(2):
                for ip in ip_list:
                    lan_turn(ip, True); lan_color(ip, colors[0]); lan_brightness(ip, 100)
                _effect_stop.wait(0.15)
                for ip in ip_list: lan_brightness(ip, 30)
                _effect_stop.wait(0.1)
            _effect_stop.wait(max(step_ms, 900) / 1000.0)

    elif effect == "lightning":
        for ip in ip_list:
            lan_turn(ip, True); lan_color(ip, colors[0]); lan_brightness(ip, 15)
        while not _effect_stop.is_set():
            _effect_stop.wait(random.uniform(2, 8))
            if _effect_stop.is_set(): break
            i = random.randrange(n)
            for _ in range(3):
                lan_color(ip_list[i], [255, 255, 255]); lan_brightness(ip_list[i], 100)
                _effect_stop.wait(0.08)
                lan_brightness(ip_list[i], 15)
                _effect_stop.wait(0.05)
            lan_color(ip_list[i], colors[0])

    elif effect == "police":
        half = max(1, n // 2)
        flip = False
        while not _effect_stop.is_set():
            flip = not flip
            for i, ip in enumerate(ip_list):
                left = i < half
                c = [255, 0, 0] if (left == flip) else [0, 40, 255]
                lan_turn(ip, True); lan_color(ip, c)
            _effect_stop.wait(max(step_ms, 100) / 1000.0)

    elif effect == "rainbow":
        for ip in ip_list: lan_turn(ip, True)
        t = 0.0
        while not _effect_stop.is_set():
            for i, ip in enumerate(ip_list):
                lan_color(ip, _hsv(i / max(n, 1) + t))
            t += 0.04
            _effect_stop.wait(max(step_ms, 80) / 1000.0)

    elif effect == "countdown":
        for ip in ip_list:
            lan_turn(ip, True); lan_color(ip, colors[0])
        total_s = max(step_ms, 3000) / 1000.0
        for i in range(n):
            if _effect_stop.is_set(): return
            _effect_stop.wait(total_s / max(n, 1))
            lan_turn(ip_list[i], False)
        for _ in range(4):
            if _effect_stop.is_set(): return
            for ip in ip_list: lan_turn(ip, True)
            _effect_stop.wait(0.15)
            for ip in ip_list: lan_turn(ip, False)
            _effect_stop.wait(0.15)
        for ip in ip_list:
            lan_turn(ip, True); lan_color(ip, colors[0])

    elif effect == "sos":
        def blink(dur):
            for ip in ip_list:
                lan_turn(ip, True); lan_color(ip, colors[0])
            _effect_stop.wait(dur)
            for ip in ip_list: lan_turn(ip, False)
            _effect_stop.wait(0.2)
        while not _effect_stop.is_set():
            for _ in range(3): blink(0.2)
            for _ in range(3): blink(0.6)
            for _ in range(3): blink(0.2)
            _effect_stop.wait(1.0)

    elif effect == "ocean":
        depths = colors or [[0, 40, 120], [0, 90, 150], [0, 140, 170], [20, 170, 180]]
        for ip in ip_list: lan_turn(ip, True)
        t = 0
        while not _effect_stop.is_set():
            for i, ip in enumerate(ip_list):
                lan_color(ip, depths[(i + t) % len(depths)])
            if random.random() < 0.3:
                lan_color(ip_list[random.randrange(n)], [120, 240, 255])
            t += 1
            _effect_stop.wait(max(step_ms, 300) / 1000.0)

    elif effect == "candycane":
        for ip in ip_list: lan_turn(ip, True)
        off = 0
        while not _effect_stop.is_set():
            for i, ip in enumerate(ip_list):
                c = [255, 0, 0] if (i + off) % 2 == 0 else [255, 255, 255]
                lan_color(ip, c)
            off += 1
            _effect_stop.wait(max(step_ms, 300) / 1000.0)

    elif effect == "jacko":
        for ip in ip_list: lan_turn(ip, True)
        while not _effect_stop.is_set():
            for ip in ip_list:
                if random.random() < 0.15:
                    lan_color(ip, [200, 30, 0]); lan_brightness(ip, random.randint(30, 70))
                else:
                    lan_color(ip, [255, 140, 20]); lan_brightness(ip, random.randint(60, 100))
            _effect_stop.wait(0.12)

    elif effect == "fireworks":
        for ip in ip_list:
            lan_turn(ip, True); lan_brightness(ip, 5)
        burst = colors or [[255, 0, 0], [0, 255, 0], [0, 120, 255], [255, 220, 0], [255, 80, 180], [255, 255, 255]]
        while not _effect_stop.is_set():
            i = random.randrange(n)
            lan_brightness(ip_list[i], 100)
            _effect_stop.wait(0.15)
            c = random.choice(burst)
            lan_color(ip_list[i], c)
            for k in range(1, min(4, n)):
                if _effect_stop.is_set(): break
                for j in range(n):
                    dist = (j - i) % n
                    if dist == k:
                        lan_color(ip_list[j], c); lan_brightness(ip_list[j], 100)
                    elif dist < k:
                        lan_color(ip_list[j], c); lan_brightness(ip_list[j], 15)
                _effect_stop.wait(0.12)
            for ip in ip_list: lan_brightness(ip, 5)
            _effect_stop.wait(random.uniform(0.5, 1.5))

    elif effect == "disco":
        for ip in ip_list: lan_turn(ip, True)
        while not _effect_stop.is_set():
            for ip in ip_list:
                lan_color(ip, _hsv(random.random()))
            _effect_stop.wait(max(step_ms, 100) / 1000.0)

    elif effect == "aurora":
        aur = colors or [[0, 200, 120], [0, 160, 180], [80, 60, 180], [40, 200, 140], [120, 80, 200]]
        for ip in ip_list: lan_turn(ip, True)
        t = 0
        while not _effect_stop.is_set():
            for i, ip in enumerate(ip_list):
                lan_color(ip, aur[(i + t) % len(aur)])
            t += 1
            _effect_stop.wait(max(step_ms, 500) / 1000.0)

    elif effect == "sunset":
        steps = [[255, 200, 60], [255, 160, 30], [255, 110, 10], [255, 60, 5], [200, 30, 0], [120, 10, 0]]
        for ip in ip_list: lan_turn(ip, True)
        for c in steps:
            if _effect_stop.is_set(): return
            for ip in ip_list: lan_color(ip, c)
            _effect_stop.wait(20)
        for b in range(90, 0, -10):
            if _effect_stop.is_set(): return
            for ip in ip_list: lan_brightness(ip, b)
            _effect_stop.wait(3)
        for ip in ip_list: lan_turn(ip, False)

    elif effect == "movie":
        for ip in ip_list:
            lan_turn(ip, True); lan_color(ip, [255, 180, 100]); lan_brightness(ip, 15)
        while not _effect_stop.is_set():
            _effect_stop.wait(1)

    elif effect in ("gradient", "solid"):
        for i, ip in enumerate(ip_list):
            c = colors[i % nc] if effect == "gradient" else colors[0]
            lan_color(ip, c); lan_turn(ip, True)
        while not _effect_stop.is_set():
            _effect_stop.wait(1)


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
        features=["9 LAN effects", "drag-and-drop layout", "presets", "zero rate limit", "setup wizard", "per-bulb control"],
    )


GITHUB_REPO = "Predator04/Groove"


def _parse_ver(v):
    import re
    try:
        parts = []
        for x in v.lstrip("v").split("."):
            m = re.match(r"\d+", x)
            parts.append(int(m.group()) if m else 0)
        return tuple((parts + [0, 0, 0])[:3])
    except Exception:
        return (0, 0, 0)


@app.route("/api/update")
def api_update():
    """Check the GitHub releases feed for a newer version (update notification only)."""
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                         headers={"Accept": "application/vnd.github+json",
                                  "User-Agent": f"Groove/{VERSION}"}, timeout=8)
        if r.status_code != 200:
            return jsonify(current=VERSION, latest=None, update_available=False,
                           error=f"release check unavailable ({r.status_code})")
        data = r.json()
        latest = data.get("tag_name", "")
        return jsonify(current=VERSION, latest=latest,
                       update_available=_parse_ver(latest) > _parse_ver(VERSION),
                       url=data.get("html_url", ""))
    except Exception as e:
        return jsonify(current=VERSION, latest=None, update_available=False, error=str(e))


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
    body = request.get_json(force=True) or {}
    dev = body.get("device")
    model = body.get("model")
    cmd = body.get("cmd")
    if not (dev and model and cmd):
        return jsonify(error="device, model and cmd are required"), 400
    return jsonify(control(dev, model, cmd))


@app.route("/api/state")
def api_state():
    if not API_KEY:
        return jsonify(error="GOVEE_API_KEY not set"), 400
    dev = request.args.get("device")
    model = request.args.get("model")
    if not (dev and model):
        return jsonify(error="device and model are required"), 400
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


@app.route("/api/current")
def api_current():
    return jsonify(CURRENT)


@app.route("/api/lan/control", methods=["POST"])
def api_lan_control():
    body = request.get_json(force=True) or {}
    ip = body.get("ip")
    cmd = body.get("cmd") or {}
    name = cmd.get("name")
    val = cmd.get("value")
    if not ip or not name:
        return jsonify(error="ip and cmd.name are required"), 400
    if name == "color":
        lan_color(ip, (val["r"], val["g"], val["b"]))
    elif name == "turn":
        lan_turn(ip, bool(val))
    elif name == "brightness":
        lan_brightness(ip, val)
    else:
        return jsonify(error=f"unknown cmd name: {name}"), 400
    return jsonify(ok=True)


def start_effect(ips, effect, colors, step_ms):
    global _effect_thread
    _effect_stop.set()
    if _effect_thread and _effect_thread.is_alive():
        _effect_thread.join(timeout=2)
    _effect_stop.clear()
    _effect_thread = threading.Thread(target=_run_effect, args=(ips, effect, colors, step_ms), daemon=True)
    _effect_thread.start()


@app.route("/api/effect/start", methods=["POST"])
def api_effect_start():
    body = request.get_json(force=True) or {}
    ips = body.get("ips") or []
    effect = body.get("effect", "chase")
    colors = body.get("colors", [[255, 0, 0]])
    step_ms = int(body.get("step_ms", 400))
    if not ips:
        return jsonify(error="ips is required"), 400
    start_effect(ips, effect, colors, step_ms)
    return jsonify(started=True, effect=effect, ips=len(ips), step_ms=step_ms)


@app.route("/api/effect/stop", methods=["POST"])
def api_effect_stop():
    _effect_stop.set()
    return jsonify(stopped=True)


@app.route("/api/lan/chase/start", methods=["POST"])
def api_lan_chase_start():
    """Backward-compat alias for the chase effect."""
    return api_effect_start()


@app.route("/api/lan/chase/stop", methods=["POST"])
def api_lan_chase_stop():
    return api_effect_stop()


# ---- visual layout dashboard (drag & drop) ----
def _load_json(name, default):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


LAYOUT = _load_json("layout.json", {})
NAMES = _load_json("names.json", {})


def refresh_names():
    global NAMES
    try:
        data = list_devices()
        for d in ((data.get("data") or {}).get("devices") or []):
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
    items = list(LAN_MAP.items())
    n = len(items)
    for i, (device_id, ip) in enumerate(items):
        pos = LAYOUT.get(device_id) or {}
        x, y = pos.get("x"), pos.get("y")
        if x is None or y is None:
            # default: spread in a horizontal chain so bulbs never pile up
            x, y = (i + 0.5) / max(n, 1), 0.5
        order = pos.get("order")
        bulbs.append({"id": device_id, "name": NAMES.get(device_id, device_id),
                      "ip": ip, "x": x, "y": y, "order": order})
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


@app.route("/setup")
def setup_page():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup.html")
    try:
        with open(p) as f:
            return f.read()
    except Exception:
        return "<h1>setup.html missing</h1>"


@app.route("/assets/<path:filename>")
def serve_asset(filename):
    from flask import send_from_directory
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    return send_from_directory(assets_dir, filename)


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


# ---- setup + discovery ----
@app.route("/api/effects")
def api_effects():
    return jsonify(["chase", "wave", "twinkle", "meteor", "breathe", "fire", "strobe",
                    "gradient", "solid", "sparkle", "heartbeat", "lightning", "police",
                    "rainbow", "countdown", "sos", "ocean", "candycane", "jacko",
                    "fireworks", "disco", "aurora", "sunset", "movie"])


@app.route("/api/scan")
def api_scan():
    """LAN discovery: multicast/broadcast scan for Govee bulbs (UDP 4001 -> 4002)."""
    found = {}
    scan = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
    try:
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx.bind(("0.0.0.0", 4002))
        rx.settimeout(1)
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            mreq = socket.inet_aton("239.255.255.250") + socket.inet_aton("0.0.0.0")
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception:
            pass
        for _ in range(4):
            tx.sendto(scan, ("239.255.255.250", 4001))
            tx.sendto(scan, ("255.255.255.255", 4001))
            while True:
                try:
                    data, addr = rx.recvfrom(65535)
                except socket.timeout:
                    break
                try:
                    j = json.loads(data)
                    d = j["msg"]["data"]
                    dev = d.get("device")
                    if dev:
                        found[dev] = {"ip": addr[0], "sku": d.get("sku"), "name": NAMES.get(dev, dev)}
                except Exception:
                    continue
        tx.close(); rx.close()
    except Exception as e:
        return jsonify({"found": found, "error": str(e)})
    return jsonify({"found": found, "count": len(found)})


@app.route("/api/setup", methods=["POST"])
def api_setup():
    """One-shot setup: save API key + LAN device map, then refresh names."""
    global LAN_MAP, API_KEY
    body = request.get_json(force=True) or {}
    cfg_dir = os.path.dirname(os.path.abspath(__file__))
    key = body.get("api_key", "")
    devices = body.get("devices", {})
    if not key and not devices:
        return jsonify(error="api_key or devices is required"), 400
    if devices:
        clean = {k: v for k, v in devices.items()
                 if isinstance(k, str) and isinstance(v, str) and v.count(".") == 3}
        if not clean:
            return jsonify(error="devices must be {device_id: ipv4}"), 400
        devices = clean
    if key:
        _write_json(os.path.join(cfg_dir, "config.json"), {"api_key": key})
        API_KEY = key
    if devices:
        _write_json(os.path.join(cfg_dir, "lan_devices.json"), devices)
        LAN_MAP = devices
    if key:
        refresh_names()
    return jsonify(saved=True, api_key=bool(key), bulbs=len(LAN_MAP))


# ---- scheduler (run an effect at a set time) ----
def _ordered_ips():
    entries = []
    for device_id, ip in LAN_MAP.items():
        pos = LAYOUT.get(device_id) or {}
        entries.append((pos.get("order"), pos.get("x", 0.5), ip))
    if entries and all(e[0] is not None for e in entries):
        entries.sort(key=lambda e: e[0])
    else:
        entries.sort(key=lambda e: e[1])
    return [e[2] for e in entries]


SCHEDULES = _load_json("schedules.json", [])


def _save_schedules():
    _write_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedules.json"), SCHEDULES)


def _scheduler_loop():
    last_fired = {}
    while True:
        try:
            now = time.localtime()
            hm = f"{now.tm_hour:02d}:{now.tm_min:02d}"
            ymd_hm = f"{now.tm_year}-{now.tm_mon:02d}-{now.tm_mday:02d} {hm}"
            wd = now.tm_wday
            for sch in list(SCHEDULES):
                if not sch.get("enabled", True): continue
                if sch.get("time") != hm: continue
                days = sch.get("days")
                if days and wd not in days: continue
                sid = sch.get("id", "")
                if last_fired.get(sid) == ymd_hm: continue
                last_fired[sid] = ymd_hm
                ips = _ordered_ips()
                if ips:
                    start_effect(ips, sch.get("effect", "chase"),
                                 sch.get("colors", [[255, 0, 0]]),
                                 int(sch.get("step_ms", 400)))
            _check_automation()
        except Exception:
            pass
        time.sleep(20)


@app.route("/api/schedules", methods=["GET"])
def api_schedules():
    return jsonify(SCHEDULES)


@app.route("/api/schedules", methods=["POST"])
def api_schedules_add():
    body = request.get_json(force=True) or {}
    sch = {
        "id": body.get("id") or f"sch{int(time.time()*1000)}",
        "time": body.get("time", ""),
        "days": body.get("days"),
        "effect": body.get("effect", "chase"),
        "colors": body.get("colors", [[255, 0, 0]]),
        "step_ms": int(body.get("step_ms", 400)),
        "name": body.get("name", ""),
        "enabled": True,
    }
    if not sch["time"]:
        return jsonify(error="time (HH:MM) is required"), 400
    SCHEDULES.append(sch)
    _save_schedules()
    return jsonify(saved=True, schedule=sch)


@app.route("/api/schedules/<sid>", methods=["DELETE"])
def api_schedules_del(sid):
    global SCHEDULES
    SCHEDULES = [s for s in SCHEDULES if s.get("id") != sid]
    _save_schedules()
    return jsonify(deleted=True)


@app.route("/api/schedules/<sid>/toggle", methods=["POST"])
def api_schedules_toggle(sid):
    for s in SCHEDULES:
        if s.get("id") == sid:
            s["enabled"] = not s.get("enabled", True)
            _save_schedules()
            return jsonify(toggled=True, enabled=s["enabled"])
    return jsonify(error="not found"), 404


# ---- sunrise/sunset automation (dusk → dawn) ----
AUTOMATION = _load_json("automation.json", {
    "enabled": False,
    "lat": 36.1699,
    "lon": -115.1398,
    "on_at_sunset": True,
    "off_at_sunrise": True,
    "effect": "solid",
    "colors": [[255, 200, 120]],
    "step_ms": 400,
})

_sun_cache = {"date": None, "sunrise": None, "sunset": None}


def _get_sun_times(lat, lon):
    import datetime as _dt
    today = _dt.date.today()
    if _sun_cache["date"] == today and _sun_cache["sunrise"] is not None:
        return _sun_cache["sunrise"], _sun_cache["sunset"]
    try:
        r = requests.get("https://api.sunrise-sunset.org/json",
                         params={"lat": lat, "lng": lon, "formatted": 0}, timeout=10)
        d = r.json().get("results", {})

        def to_min(iso):
            dt = _dt.datetime.fromisoformat(iso)  # aware UTC
            local = dt.astimezone()
            return local.hour * 60 + local.minute
        sunrise = to_min(d["sunrise"])
        sunset = to_min(d["sunset"])
        _sun_cache.update({"date": today, "sunrise": sunrise, "sunset": sunset})
        return sunrise, sunset
    except Exception:
        return None, None


_auto_on = False


def _check_automation():
    global _auto_on
    if not AUTOMATION.get("enabled"):
        return
    now = time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    sr, ss = _get_sun_times(AUTOMATION.get("lat"), AUTOMATION.get("lon"))
    if sr is None:
        return
    nighttime = (cur >= ss) or (cur < sr)
    if nighttime and AUTOMATION.get("on_at_sunset") and not _auto_on:
        _auto_on = True
        ips = _ordered_ips()
        if ips:
            start_effect(ips, AUTOMATION.get("effect", "chase"),
                         AUTOMATION.get("colors", [[255, 200, 120]]),
                         int(AUTOMATION.get("step_ms", 400)))
    elif not nighttime and AUTOMATION.get("off_at_sunrise") and _auto_on:
        _auto_on = False
        _effect_stop.set()
        for ip in LAN_MAP.values():
            lan_turn(ip, False)


@app.route("/api/automation", methods=["GET"])
def api_automation():
    sr, ss = _get_sun_times(AUTOMATION.get("lat"), AUTOMATION.get("lon"))
    def fmt(m):
        return f"{m//60:02d}:{m%60:02d}" if m is not None else None
    return jsonify({**AUTOMATION, "sunrise": fmt(sr), "sunset": fmt(ss)})


@app.route("/api/automation", methods=["POST"])
def api_automation_set():
    global AUTOMATION
    body = request.get_json(force=True) or {}
    for k in ("enabled", "lat", "lon", "on_at_sunset", "off_at_sunrise", "effect", "colors", "step_ms", "zip", "city", "state"):
        if k in body:
            AUTOMATION[k] = body[k]
    _write_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), "automation.json"), AUTOMATION)
    return jsonify(saved=True, automation=AUTOMATION)


@app.route("/api/geocode")
def api_geocode():
    zipc = request.args.get("zip", "").strip()
    if not zipc:
        return jsonify(error="zip is required"), 400
    try:
        r = requests.get(f"https://api.zippopotam.us/us/{zipc}", timeout=10)
        if r.status_code != 200:
            return jsonify(error=f"zip not found ({r.status_code})"), 404
        d = r.json()
        place = d["places"][0]
        return jsonify(zip=zipc,
                       lat=float(place["latitude"]), lon=float(place["longitude"]),
                       city=place.get("place name", ""), state=place.get("state", ""))
    except Exception as e:
        return jsonify(error=str(e)), 500


# ---- scenes (save/recall per-bulb colors) + trigger URL ----
SCENES = _load_json("scenes.json", {})


def _save_scenes():
    _write_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenes.json"), SCENES)


@app.route("/api/scenes", methods=["GET"])
def api_scenes():
    return jsonify(SCENES)


@app.route("/api/scenes", methods=["POST"])
def api_scenes_save():
    global SCENES
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    state = body.get("state") or {}
    if not name or not state:
        return jsonify(error="name and state are required"), 400
    SCENES[name] = state
    _save_scenes()
    return jsonify(saved=True, name=name, bulbs=len(state))


@app.route("/api/scenes/<name>", methods=["DELETE"])
def api_scenes_del(name):
    global SCENES
    if name in SCENES:
        del SCENES[name]
        _save_scenes()
        return jsonify(deleted=True)
    return jsonify(error="not found"), 404


@app.route("/api/scenes/<name>/apply", methods=["POST"])
def api_scenes_apply(name):
    state = SCENES.get(name)
    if not state:
        return jsonify(error="scene not found"), 404
    for ip, rgb in state.items():
        lan_turn(ip, True)
        lan_color(ip, rgb)
    return jsonify(applied=True, name=name, bulbs=len(state))


@app.route("/trigger/<name>")
def trigger_scene(name):
    """Public trigger URL — hit /trigger/<scene> to recall a scene (Siri, Stream Deck, bookmark)."""
    state = SCENES.get(name)
    if not state:
        return jsonify(error="unknown trigger"), 404
    for ip, rgb in state.items():
        lan_turn(ip, True)
        lan_color(ip, rgb)
    return jsonify(applied=True, name=name)


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
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8813)), debug=False)
