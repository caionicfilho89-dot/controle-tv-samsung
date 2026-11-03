"""Atalho "Tela na TV": liga a transmissão da tela 2 e abre ela no navegador da TV."""
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tvkeys_lib  # noqa: E402

PORT = 8090
BROWSER_ID = "3201907018784"  # app "Internet" da TV

# um clique de cada vez: dois rodando juntos ficam abrindo e fechando o navegador da TV
_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "ClaudePC.LigarTelaTV")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    sys.exit(0)


def pc_ip(tv_ip):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((tv_ip, 8001))
        return s.getsockname()[0]


def viewers():
    """Quantos navegadores estão assistindo; None se a transmissão não está rodando."""
    try:
        return int(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/assistindo", timeout=2).read())
    except Exception:
        return None


# volta a usar a TV como tela 2 (o "Encerrar" deixa o PC só no Odyssey)
subprocess.run(["DisplaySwitch.exe", "/extend"], creationflags=subprocess.CREATE_NO_WINDOW)
time.sleep(3)

if viewers() is None:
    subprocess.Popen([sys.executable, os.path.join(HERE, "tela_tv.py"), str(PORT)],
                     creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(20):
        time.sleep(0.5)
        if viewers() is not None:
            break

# a página da TV se reconecta sozinha: espera um pouco antes de mexer no navegador
for _ in range(5):
    if viewers():
        sys.exit(0)
    time.sleep(1)

tv_ip = tvkeys_lib.find_tv()
if not tv_ip:
    tvkeys_lib.aviso("Não achei a TV na rede. Ela está ligada?")
    sys.exit(1)

app_url = f"http://{tv_ip}:8001/api/v2/applications/{BROWSER_ID}"


def browser_visible():
    try:  # a TV demora uns 5 s pra responder enquanto recebe a transmissão
        with urllib.request.urlopen(app_url, timeout=12) as r:
            return json.load(r).get("visible")
    except Exception:
        return False


try:  # fecha o navegador se já estiver aberto, pra começar sempre do mesmo jeito
    urllib.request.urlopen(urllib.request.Request(app_url, method="DELETE"), timeout=12).read()
    time.sleep(3)
except Exception:
    pass

urllib.request.urlopen(urllib.request.Request(app_url, method="POST"), timeout=12).read()
deadline = time.time() + 30
while not browser_visible():
    if time.time() > deadline:
        tvkeys_lib.aviso("Não consegui abrir o navegador da TV.")
        sys.exit(1)
    time.sleep(1)
time.sleep(4)  # espera a página inicial do navegador carregar
tvkeys_lib.send(["KEY_UP", "KEY_UP", "KEY_UP", "KEY_ENTER", 2,
                 f"text={pc_ip(tv_ip)}:{PORT}", 1, "KEY_ENTER",
                 # a TV costuma bloquear o som no autoplay; o ENTER depois da página carregar conta como
                 # "gesto do usuário" e libera o áudio
                 6, "KEY_ENTER"])
