import socket, json

scan = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
rx.bind(("0.0.0.0", 4002))
rx.settimeout(1)
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
found = {}
for _ in range(4):
    tx.sendto(scan, ("239.255.255.250", 4001))
    tx.sendto(scan, ("255.255.255.255", 4001))
    while True:
        try:
            data, addr = rx.recvfrom(65535)
        except socket.timeout:
            break
        try:
            d = json.loads(data)["msg"]["data"]
            if d.get("device"):
                found[d["device"]] = (addr[0], d.get("sku"))
        except Exception:
            pass
tx.close(); rx.close()
for dev, (ip, sku) in sorted(found.items(), key=lambda kv: kv[1][0]):
    print(f"{dev}\t{ip}\t{sku}")
print("COUNT", len(found))
