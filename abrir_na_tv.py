"""Abre um endereço no navegador da TV: python abrir_na_tv.py http://..."""
import json
import sys
import time

import websocket

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from tvkeys_lib import connect  # noqa: E402

url = sys.argv[1]
ws = connect()
ws.send(json.dumps({"method": "ms.channel.emit", "params": {
    "event": "ed.apps.launch", "to": "host",
    "data": {"appId": "3201907018784", "action_type": "DEEP_LINK", "metaTag": url}}}))
time.sleep(1.5)
ws.close()
print("aberto", url)
