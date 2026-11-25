import socket, json, time, sys
sys.stdout.reconfigure(errors='replace')

SCAN = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()

rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
rx.bind(("0.0.0.0", 4002))
rx.settimeout(1)

tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
try:
    mreq = socket.inet_aton("239.255.255.250") + socket.inet_aton("0.0.0.0")
    tx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
except Exception as e:
    print("mcast join:", e)

found = {}
for round_i in range(5):
    tx.sendto(SCAN, ("239.255.255.250", 4001))
    tx.sendto(SCAN, ("255.255.255.255", 4001))
    # drain responses for 1s
    while True:
        try:
            data, addr = rx.recvfrom(65535)
            try:
                j = json.loads(data)
                dd = j["msg"]["data"]
                found[dd.get("device")] = (addr[0], dd.get("sku"), dd.get("wifiVersionSoft"))
            except Exception:
                pass
        except socket.timeout:
            break

print("unique bulbs responding:", len(found))
for dev, (ip, sku, ws) in sorted(found.items(), key=lambda x: x[1][0]):
    print(f"  {ip}: {dev} sku={sku} wifiSoft={ws}")
