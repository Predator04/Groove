import socket, json, time, sys
sys.stdout.reconfigure(errors='replace')

SCAN = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()

rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    rx.bind(("0.0.0.0", 4002))
except OSError as e:
    print("bind 4002 failed:", e)
    sys.exit(1)
rx.settimeout(6)

tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
# try multicast membership too
try:
    mreq = socket.inet_aton("239.255.255.250") + socket.inet_aton("0.0.0.0")
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
except Exception as e:
    print("mcast join:", e)

tx.sendto(SCAN, ("239.255.255.250", 4001))
tx.sendto(SCAN, ("255.255.255.255", 4001))
print("scan sent")

found = []
deadline = time.time() + 6
while time.time() < deadline:
    try:
        data, addr = rx.recvfrom(65535)
        found.append((addr[0], data.decode(errors='replace')))
    except socket.timeout:
        break

print("responses:", len(found))
for ip, d in found:
    try:
        j = json.loads(d)
        dd = j.get("msg", {}).get("data", {})
        print(f"  {ip}: device={dd.get('device')} sku={dd.get('sku')} wifiSoft={dd.get('wifiVersionSoft')}")
    except Exception:
        print(f"  {ip}: {d[:200]}")
