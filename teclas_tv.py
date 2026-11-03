"""Envia teclas/texto pra TV: python teclas_tv.py KEY_UP wait=1 text=abc KEY_ENTER"""
import base64
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from tvkeys_lib import connect  # noqa: E402

ws = connect()
for k in sys.argv[1:]:
    if k.startswith("wait="):
        time.sleep(float(k[5:]))
        continue
    if k.startswith("text="):
        ws.send(json.dumps({"method": "ms.remote.control", "params": {
            "Cmd": base64.b64encode(k[5:].encode()).decode(), "DataOfCmd": "base64",
            "TypeOfRemote": "SendInputString"}}))
        time.sleep(0.4)
        ws.send(json.dumps({"method": "ms.remote.control", "params": {"TypeOfRemote": "SendInputEnd"}}))
    else:
        ws.send(json.dumps({"method": "ms.remote.control", "params": {
            "Cmd": "Click", "DataOfCmd": k, "Option": "false", "TypeOfRemote": "SendRemoteKey"}}))
    print("enviado", k)
    time.sleep(0.8)
ws.close()
