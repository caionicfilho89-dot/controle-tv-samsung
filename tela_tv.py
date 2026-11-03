"""Transmite a tela 2 do Windows (a TV) para o navegador da TV pela rede.

Vídeo: quadros JPEG num fluxo MJPEG (/stream).
Som:   o áudio do sistema (loopback) capturado e recomprimido em MP3 ao vivo (/audio), tocado por um
       <audio> na página — assim a aula/vídeo vai para a TV com imagem E som, não só a imagem.

Uso: python tela_tv.py [porta]   -> depois abra http://<ip-do-pc>:<porta>/ na TV
"""
import ctypes
import io
import queue
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mss
from PIL import Image, ImageDraw

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
FPS = 15
QUALITY = 70

AUDIO_SR = 48000
AUDIO_CH = 2
CREATE_NO_WINDOW = 0x08000000   # não pisca janela de console ao rodar o ffmpeg

# O som do sistema (loopback) precisa do soundcard + numpy e do ffmpeg. Sem eles, só o vídeo vai (como antes).
try:
    import numpy as np
    import soundcard as sc
    HAVE_AUDIO = True
except Exception:  # noqa: BLE001
    HAVE_AUDIO = False

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Tela do PC</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
img{width:100vw;height:100vh;object-fit:contain;display:block}</style></head>
<body><img id="v"><audio id="a" autoplay playsinline></audio>
<script>
// se a transmissão cair (PC reiniciou o programa), tenta de novo sozinho
var v = document.getElementById("v"), a = document.getElementById("a");
function startV() { v.src = "/stream?t=" + Date.now(); }
v.onerror = function () { setTimeout(startV, 2000); };
function startA() { a.src = "/audio?t=" + Date.now(); if (a.play) a.play().catch(function(){}); }
a.onerror = function () { setTimeout(startA, 2000); };
// a TV pode bloquear o som no autoplay: qualquer tecla (o ENTER do controle) ou toque libera
function kick() { a.muted = false; if (a.play) a.play().catch(function(){}); }
document.addEventListener("keydown", kick);
document.addEventListener("click", kick);
startV(); startA();
</script></body></html>""".encode("utf-8")


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor_pos():
    p = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def tv_monitor(sct):
    """Prefer the secondary screen (the TV); fall back to the primary one."""
    others = [m for m in sct.monitors[1:] if (m["left"], m["top"]) != (0, 0)]
    return others[0] if others else sct.monitors[1]


latest = {"jpg": b"", "n": 0}
viewers = {"n": 0}  # quantos navegadores estão assistindo agora
cond = threading.Condition()


def capture():
    ctypes.windll.user32.SetProcessDPIAware()
    last = None
    with mss.mss() as sct:
        while True:
            t0 = time.time()
            mon = tv_monitor(sct)
            shot = sct.grab(mon)
            cx, cy = cursor_pos()
            cx, cy = cx - mon["left"], cy - mon["top"]
            # nothing changed (static slide, paused video): don't make the TV decode the same image again
            key = (hash(shot.bgra), cx, cy)
            if key == last:
                time.sleep(1 / FPS)
                continue
            last = key
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            if 0 <= cx < mon["width"] and 0 <= cy < mon["height"]:
                s = max(12, mon["height"] // 45)
                ImageDraw.Draw(img).polygon(
                    [(cx, cy), (cx, cy + s), (cx + s * 0.3, cy + s * 0.75), (cx + s * 0.7, cy + s * 0.7)],
                    fill="white", outline="black")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=QUALITY)
            with cond:
                latest["jpg"] = buf.getvalue()
                latest["n"] += 1
                cond.notify_all()
            time.sleep(max(0, 1 / FPS - (time.time() - t0)))


class AudioHub:
    """Captura o som que o PC está tocando (loopback) e o entrega em MP3 ao vivo para quem pedir /audio.
    O ffmpeg recomprime o PCM em MP3; cada navegador ligado recebe o fluxo a partir de agora."""

    def __init__(self):
        self.clients = set()      # uma fila por navegador ligado
        self.lock = threading.Lock()
        self.ok = False           # o ffmpeg subiu e está produzindo MP3
        self.run = True
        self.proc = None

    def start(self):
        if not HAVE_AUDIO:
            return
        ff = shutil.which("ffmpeg")
        if not ff:
            return
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "s16le", "-ar", str(AUDIO_SR), "-ac", str(AUDIO_CH), "-i", "pipe:0",
               "-c:a", "libmp3lame", "-b:a", "160k", "-f", "mp3", "-flush_packets", "1", "pipe:1"]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        except OSError:
            return
        self.ok = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._capture, daemon=True).start()

    def add(self):
        q = queue.Queue(maxsize=48)   # ~48 pedaços de MP3; se o navegador atrasa, descarta o antigo p/ não acumular
        with self.lock:
            self.clients.add(q)
        return q

    def remove(self, q):
        with self.lock:
            self.clients.discard(q)

    def _broadcast(self, chunk):
        with self.lock:
            cs = list(self.clients)
        for q in cs:
            try:
                q.put_nowait(chunk)
            except queue.Full:
                try:        # mantém ao vivo: joga fora o pedaço mais antigo e põe o novo
                    q.get_nowait()
                    q.put_nowait(chunk)
                except queue.Empty:
                    pass

    def _reader(self):
        """Lê o MP3 que sai do ffmpeg e repassa a todos os navegadores ligados."""
        out = self.proc.stdout
        while self.run:
            chunk = out.read(4096)
            if not chunk:
                break
            self._broadcast(chunk)
        self.ok = False

    def _capture(self):
        """Lê o som do sistema (loopback do alto-falante padrão) e alimenta o ffmpeg. Reabre sozinho se o
        dispositivo de som mudar ou engasgar."""
        while self.run and self.proc and self.proc.poll() is None:
            try:
                spk = sc.default_speaker()
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
                with mic.recorder(samplerate=AUDIO_SR, channels=AUDIO_CH, blocksize=1024) as rec:
                    while self.run and self.proc.poll() is None:
                        data = rec.record(numframes=2048)   # ~43 ms
                        pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                        self.proc.stdin.write(pcm)
            except Exception:  # noqa: BLE001 - dispositivo de som trocou/sumiu: tenta de novo
                if not self.run:
                    break
                time.sleep(1.0)


audio = AudioHub()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/parar" and self.client_address[0] == "127.0.0.1":
            self.send_response(200)
            self.end_headers()
            threading.Thread(target=server.shutdown, daemon=True).start()
        elif self.path == "/assistindo":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(str(viewers["n"]).encode())
        elif self.path.startswith("/audio"):
            if not audio.ok:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            q = audio.add()
            try:
                while True:
                    self.wfile.write(q.get(timeout=10))
            except (ConnectionError, OSError, queue.Empty):
                return
            finally:
                audio.remove(q)
        elif self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            seen = -1
            viewers["n"] += 1
            try:
                while True:
                    with cond:
                        cond.wait_for(lambda: latest["n"] != seen, timeout=5)
                        jpg, seen = latest["jpg"], latest["n"]
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            except (ConnectionError, OSError):
                return
            finally:
                viewers["n"] -= 1
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)


threading.Thread(target=capture, daemon=True).start()
audio.start()
print(f"Transmitindo na porta {PORT}", flush=True)
server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
server.daemon_threads = True
server.serve_forever()
