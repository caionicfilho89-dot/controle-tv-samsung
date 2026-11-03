"""Acha a TV na rede pelo MAC e abre o websocket do controle."""
import base64
import ctypes
import json
import os
import ssl
import sys
import threading
import time
import urllib.request

import websocket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tvconf  # noqa: E402  (o MAC/IP da sua TV ficam em tv_config.json, fora do git)

MAC = tvconf.tv_mac()
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")


def _mac_at(ip, timeout=1.5):
    try:
        with urllib.request.urlopen(f"http://{ip}:8001/api/v2/", timeout=timeout) as r:
            return json.load(r).get("device", {}).get("wifiMac", "").upper()
    except Exception:
        return None


LAST_IP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultimo_ip.txt")


def find_tv(prefix=None):
    if prefix is None:
        prefix = tvconf.tv_ip().rsplit(".", 1)[0]
    if os.path.exists(LAST_IP_FILE):
        last = open(LAST_IP_FILE).read().strip()
        if _mac_at(last, timeout=10) == MAC:  # lenta enquanto a TV recebe a transmissão
            return last
    ip = _scan(prefix) or _scan(prefix)
    if ip:
        with open(LAST_IP_FILE, "w") as f:
            f.write(ip)
    return ip


def _scan(prefix):
    found = []
    threads = [threading.Thread(target=lambda ip=f"{prefix}.{i}": _mac_at(ip) == MAC and found.append(ip),
                                daemon=True) for i in range(1, 255)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(3)
    return found[0] if found else None


def connect():
    ip = find_tv()
    if not ip:
        raise SystemExit("TV não encontrada na rede (está ligada?)")
    name = base64.b64encode(b"ClaudePC").decode()
    url = f"wss://{ip}:8002/api/v2/channels/samsung.remote.control?name={name}"
    if os.path.exists(TOKEN_FILE):
        url += "&token=" + open(TOKEN_FILE).read().strip()
    ws = websocket.create_connection(url, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=30)
    msg = json.loads(ws.recv())
    if msg.get("event") != "ms.channel.connect":
        raise SystemExit("TV recusou a conexão: " + str(msg.get("event")))
    return ws


def send(steps):
    """Teclas ("KEY_UP"), texto ("text=abc") e pausas em segundos (números)."""
    ws = connect()
    for step in steps:
        if isinstance(step, (int, float)):
            time.sleep(step)
            continue
        if step.startswith("text="):
            ws.send(json.dumps({"method": "ms.remote.control", "params": {
                "Cmd": base64.b64encode(step[5:].encode()).decode(), "DataOfCmd": "base64",
                "TypeOfRemote": "SendInputString"}}))
            time.sleep(0.4)
            ws.send(json.dumps({"method": "ms.remote.control", "params": {"TypeOfRemote": "SendInputEnd"}}))
        else:
            ws.send(json.dumps({"method": "ms.remote.control", "params": {
                "Cmd": "Click", "DataOfCmd": step, "Option": "false", "TypeOfRemote": "SendRemoteKey"}}))
        time.sleep(0.8)
    ws.close()


def aviso(texto):
    ctypes.windll.user32.MessageBoxW(None, texto, "Tela na TV", 0x40)
