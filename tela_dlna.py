r"""Manda a tela do PC (com som) para a TV por DLNA — do mesmo jeito que o Pudim manda filme
(SSDP + SOAP na porta 9197). Não usa o navegador da TV nem o canal que pede "Permitir".

A tela é capturada pelo ffmpeg (H.264) e o som do sistema pelo soundcard (loopback), juntos num
MPEG-TS ao vivo que o player da própria TV toca.

Uso:  python tela_dlna.py          liga
      python tela_dlna.py parar    desliga
"""
import ctypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
PORT_FILE = os.path.join(HERE, "dlna_port.txt")
SSDP_ST = "urn:schemas-upnp-org:service:AVTransport:1"
DLNA_LIVE = "DLNA.ORG_OP=00;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"
CREATE_NO_WINDOW = 0x08000000
FPS = 20

try:
    import numpy as np
    import soundcard as sc
    HAVE_AUDIO = True
except Exception:  # noqa: BLE001
    HAVE_AUDIO = False


def ip_towards(target, port=80):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target, port))
        return s.getsockname()[0]


def find_renderer(timeout=3):
    """Endereço de controle (AVTransport) da TV, achado por SSDP — o mesmo canal do Pudim."""
    msg = (f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
           f"ST: {SSDP_ST}\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.bind((ip_towards("8.8.8.8"), 0))
        s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                break
            m = re.search(rb"(?i)location:\s*(\S+)", data)
            if not m:
                continue
            try:
                desc = urllib.request.urlopen(m.group(1).decode(), timeout=5).read().decode("utf8", "ignore")
            except OSError:
                continue
            ctrl = re.search(r"AVTransport:1</serviceType>.*?<controlURL>(.*?)</controlURL>", desc, re.S)
            if ctrl:
                return urllib.parse.urljoin(m.group(1).decode(), ctrl.group(1).strip())
    finally:
        s.close()
    return None


def soap(ctrl, action, args="", timeout=15):
    body = (f'<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{action} '
            f'xmlns:u="{SSDP_ST}"><InstanceID>0</InstanceID>{args}</u:{action}></s:Body></s:Envelope>').encode()
    req = urllib.request.Request(ctrl, data=body, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{SSDP_ST}#{action}"'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf8", "ignore")
    except OSError as e:
        return 0, str(e)


def primary_size():
    u = ctypes.windll.user32
    u.SetProcessDPIAware()
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def ffmpeg_cmd(w, h, audio):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-f", "gdigrab", "-framerate", str(FPS), "-offset_x", "0", "-offset_y", "0",
           "-video_size", f"{w}x{h}", "-i", "desktop"]
    if audio:
        cmd += ["-f", "s16le", "-ar", "48000", "-ac", "2", "-thread_queue_size", "4096", "-i", "pipe:0"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
            "-g", str(FPS * 2), "-b:v", "6M", "-maxrate", "6M", "-bufsize", "8M"]
    if audio:
        # começa os dois em ~0 e não deixa o muxer travar esperando um stream: evita o "carregando sem fim"
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-map", "0:v:0", "-map", "1:a:0",
                "-af", "aresample=async=1:first_pts=0",
                "-muxdelay", "0", "-muxpreload", "0", "-max_interleave_delta", "0"]
    cmd += ["-f", "mpegts", "pipe:1"]
    return cmd


class Server:
    def __init__(self, audio=True):
        self.w, self.h = primary_size()
        self.audio = audio and HAVE_AUDIO
        self.proc = None
        self.stop_event = threading.Event()
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a):
                pass

            def _dlna_headers(self):
                self.send_header("Content-Type", "video/mp2t")
                self.send_header("transferMode.dlna.org", "Streaming")
                self.send_header("contentFeatures.dlna.org", DLNA_LIVE)
                self.send_header("Connection", "close")
                self.end_headers()

            def do_HEAD(self):
                self.send_response(200)
                self._dlna_headers()

            def do_GET(self):
                if self.path == "/parar" and self.client_address[0] == "127.0.0.1":
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    server.stop_event.set()
                    return
                if not self.path.startswith("/screen"):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self._dlna_headers()
                server.stream_to(self.wfile)

        self.http = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.http.daemon_threads = True
        self.http.handle_error = lambda *_a: None
        self.port = self.http.server_address[1]

    def serve(self):
        with open(PORT_FILE, "w") as f:
            f.write(str(self.port))
        threading.Thread(target=self.http.serve_forever, name="dlna-screen", daemon=True).start()

    def stream_to(self, wfile):
        self._kill()
        audio = self.audio
        proc = subprocess.Popen(ffmpeg_cmd(self.w, self.h, audio),
                                stdin=(subprocess.PIPE if audio else None),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=CREATE_NO_WINDOW)
        self.proc = proc
        if audio:
            threading.Thread(target=self._audio_loop, args=(proc,), daemon=True).start()
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                wfile.write(chunk)
        except (OSError, ValueError):
            pass
        finally:
            if self.proc is proc:
                self._kill()

    def _audio_loop(self, proc):
        """Som do sistema (loopback do alto-falante padrão) -> stdin do ffmpeg."""
        try:
            spk = sc.default_speaker()
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            with mic.recorder(samplerate=48000, channels=2, blocksize=1024) as rec:
                while self.proc is proc and proc.poll() is None:
                    data = rec.record(numframes=2048)
                    try:
                        proc.stdin.write((np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
                    except (OSError, ValueError):
                        break
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

    def _kill(self):
        if self.proc:
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
            self.proc = None


def do_stop():
    """Desliga uma transmissão que esteja rodando e manda a TV parar."""
    try:
        port = int(open(PORT_FILE).read().strip())
        urllib.request.urlopen(f"http://127.0.0.1:{port}/parar", timeout=3).read()
    except Exception:  # noqa: BLE001
        pass
    ctrl = find_renderer()
    if ctrl:
        soap(ctrl, "Stop", timeout=8)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "parar":
        do_stop()
        return 0
    ctrl = find_renderer()
    if not ctrl:
        print("Não achei a TV na rede (SSDP). Ela está ligada e na mesma rede?")
        return 1
    srv = Server(audio="mudo" not in sys.argv)
    srv.serve()
    host = urllib.parse.urlsplit(ctrl).hostname
    link = f"http://{ip_towards(host)}:{srv.port}/screen.ts"
    print("Transmitindo tela em:", link, f"({srv.w}x{srv.h})", "com som" if srv.audio else "sem som")
    didl = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            '<item id="1" parentID="0" restricted="1"><dc:title>Tela do PC</dc:title>'
            '<upnp:class>object.item.videoItem.videoBroadcast</upnp:class>'
            f'<res protocolInfo="http-get:*:video/mp2t:{DLNA_LIVE}">{escape(link)}</res>'
            '</item></DIDL-Lite>')
    soap(ctrl, "Stop", timeout=8)
    code, resp = soap(ctrl, "SetAVTransportURI",
                      f"<CurrentURI>{escape(link)}</CurrentURI><CurrentURIMetaData>{escape(didl)}</CurrentURIMetaData>")
    if code != 200:
        print("SetAVTransportURI falhou:", code, resp[:200])
        return 1
    time.sleep(1.0)
    soap(ctrl, "Play", "<Speed>1</Speed>")
    print("No ar. (python tela_dlna.py parar) para desligar.")
    try:
        srv.stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        soap(ctrl, "Stop", timeout=8)
        srv._kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
