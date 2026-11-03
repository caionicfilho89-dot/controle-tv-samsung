"""Encerra a "Tela na TV": para a transmissão, fecha o navegador da TV e deixa o PC só no Odyssey."""
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tvkeys_lib  # noqa: E402

PORT = 8090
BROWSER_ID = "3201907018784"  # app "Internet" da TV

try:
    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/parar", timeout=3).read()
except Exception:
    pass  # já estava parada

# só a tela principal: assim nenhuma janela nem o mouse vão parar na TV sem você ver
subprocess.run(["DisplaySwitch.exe", "/internal"], creationflags=subprocess.CREATE_NO_WINDOW)

tv_ip = tvkeys_lib.find_tv()
if tv_ip:
    try:
        req = urllib.request.Request(f"http://{tv_ip}:8001/api/v2/applications/{BROWSER_ID}", method="DELETE")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass
