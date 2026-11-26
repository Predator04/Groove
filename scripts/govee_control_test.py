import socket, json, time, sys
sys.stdout.reconfigure(errors='replace')

IP = "192.168.1.50"  # <-- your bulb's LAN IP here
PORT = 4003

def fire(cmd, data):
    msg = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(msg, (IP, PORT))
    s.close()

def query(cmd, data):
    msg = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    s.sendto(msg, (IP, PORT))
    try:
        resp, _ = s.recvfrom(65535)
        return resp.decode(errors='replace')
    except socket.timeout:
        return "(no response)"
    finally:
        s.close()

print("status before:", query("devStatus", {}))
fire("turn", {"value": 1})
time.sleep(0.3)
fire("colorwc", {"color": {"r":255,"g":0,"b":0}, "colorTemInKelvin": 0})
time.sleep(0.5)
print("status after red:", query("devStatus", {}))

# rapid fire: 30 color changes, no ACK wait (proves no throttle)
t0 = time.time()
for i in range(30):
    fire("colorwc", {"color": {"r":(i*37)%256,"g":(i*89)%256,"b":(i*131)%256}, "colorTemInKelvin": 0})
    time.sleep(0.05)
dt = time.time() - t0
print(f"sent 30 color cmds in {dt:.2f}s ({30/dt:.1f}/s) — no throttle")
time.sleep(0.5)
print("final status:", query("devStatus", {}))
