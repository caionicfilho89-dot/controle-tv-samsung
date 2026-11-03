"""Controle remoto da TV Samsung (Tizen) pelo PC."""
import base64
import json
import math
import os
import queue
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request

import websocket
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPainterPath,
                         QPen, QPixmap, QShortcut)
from PyQt6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMenu, QPushButton, QSizePolicy, QSystemTrayIcon, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tvconf  # noqa: E402  (o MAC/IP da sua TV ficam em tv_config.json, fora do git)
LAST_IP_FILE = tvconf.LAST_IP_FILE
TV_MAC = tvconf.tv_mac()
TV_IP = tvconf.tv_ip()
TOKEN_FILE = os.path.join(HERE, "token.txt")
SETTINGS_FILE = os.path.join(HERE, "config.json")
APP_NAME = base64.b64encode(b"ClaudePC").decode()

# Smarters can't be launched by id on this TV: it is pinned on the home bar right after
# the ad tile, so open home and walk to it (number = seconds to wait)
SMARTERS_MACRO = ["KEY_HOME", 2.5, "KEY_RIGHT", 0.6, "KEY_RIGHT", 0.8, "KEY_ENTER"]

# name, id (or macro), tile color
APPS = [
    ("Smarters", SMARTERS_MACRO, "#4b2bd6"),
    ("YouTube", "111299001912", "#e62117"),
    ("Netflix", "3201907018807", "#b20710"),
    ("Prime Video", "3201910019365", "#1a98ff"),
    ("Disney+", "3201901017640", "#0b3d91"),
    ("Globoplay", "3201908019041", "#f2243b"),
    ("Spotify", "3201606009684", "#1db954"),
    ("Twitch", "3202203026841", "#9146ff"),
]

# tecla do PC -> tecla da TV
KEYBOARD = {
    Qt.Key.Key_Up: "KEY_UP", Qt.Key.Key_Down: "KEY_DOWN", Qt.Key.Key_Left: "KEY_LEFT",
    Qt.Key.Key_Right: "KEY_RIGHT", Qt.Key.Key_Return: "KEY_ENTER", Qt.Key.Key_Enter: "KEY_ENTER",
    Qt.Key.Key_Backspace: "KEY_RETURN", Qt.Key.Key_Escape: "KEY_EXIT", Qt.Key.Key_Plus: "KEY_VOLUP",
    Qt.Key.Key_Minus: "KEY_VOLDOWN", Qt.Key.Key_M: "KEY_MUTE", Qt.Key.Key_H: "KEY_HOME",
    Qt.Key.Key_S: "KEY_SOURCE", Qt.Key.Key_Space: "KEY_PLAY", Qt.Key.Key_PageUp: "KEY_CHUP",
    Qt.Key.Key_PageDown: "KEY_CHDOWN", Qt.Key.Key_I: "KEY_INFO",
    **{getattr(Qt.Key, f"Key_{n}"): f"KEY_{n}" for n in range(10)},
}

# Segoe Fluent Icons glyphs
IC = {
    "power": "", "home": "", "back": "", "close": "", "menu": "",
    "source": "", "info": "", "volup": "", "voldown": "", "mute": "",
    "play": "", "pause": "", "stop": "", "rew": "", "ff": "",
    "up": "", "down": "", "left": "", "right": "", "pin": "",
    "unpin": "", "keyboard": "", "send": "", "dial": "", "tv": "",
}

T = {  # theme
    "bg": "#0f1115", "card": "#181b22", "btn": "#232733", "btn_hi": "#2e3443", "btn_dn": "#3a4256",
    "fg": "#eef0f4", "dim": "#8b92a1", "faint": "#555c6b", "accent": "#4c7dff", "red": "#e5484d",
    "green": "#3dd68c",
}


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


class Remote:
    """Persistent websocket to the TV; every command runs on one worker thread, in order."""

    def __init__(self, on_result):
        self.ws = None
        self.jobs = queue.Queue()
        self.on_result = on_result
        threading.Thread(target=self._worker, daemon=True).start()

    def _connect(self):
        find_tv()
        url = f"wss://{TV_IP}:8002/api/v2/channels/samsung.remote.control?name={APP_NAME}"
        if os.path.exists(TOKEN_FILE):
            url += "&token=" + open(TOKEN_FILE).read().strip()
        ws = websocket.create_connection(url, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=30)
        msg = json.loads(ws.recv())
        if msg.get("event") != "ms.channel.connect":
            ws.close()
            raise ConnectionError(msg.get("event", "recusado"))
        token = msg.get("data", {}).get("token")
        if token:
            with open(TOKEN_FILE, "w") as f:
                f.write(token)
        ws.settimeout(5)
        self.ws = ws

    def _send_json(self, payload):
        for attempt in range(2):
            try:
                if self.ws is None:
                    self._connect()
                self.ws.send(json.dumps(payload))
                return
            except Exception:
                self.ws = None
                if attempt:
                    raise

    def _worker(self):
        while True:
            fn, label = self.jobs.get()
            try:
                fn()
                self.on_result(True, label)
            except Exception as e:
                self.on_result(False, f"TV não respondeu ({type(e).__name__})")

    def _key(self, key):
        self._send_json({"method": "ms.remote.control", "params": {
            "Cmd": "Click", "DataOfCmd": key, "Option": "false", "TypeOfRemote": "SendRemoteKey"}})

    def key(self, key):
        self.jobs.put((lambda: self._key(key), key.replace("KEY_", "")))

    def text(self, text):
        def job():
            self._send_json({"method": "ms.remote.control", "params": {
                "Cmd": base64.b64encode(text.encode()).decode(), "DataOfCmd": "base64",
                "TypeOfRemote": "SendInputString"}})
            time.sleep(0.3)
            self._send_json({"method": "ms.remote.control", "params": {"TypeOfRemote": "SendInputEnd"}})
        self.jobs.put((job, "Texto enviado"))

    def macro(self, steps, label):
        def job():
            for step in steps:
                if isinstance(step, str):
                    self._key(step)
                else:
                    time.sleep(step)
        self.jobs.put((job, label))

    def launch(self, app_id, label):
        def job():
            req = urllib.request.Request(f"http://{TV_IP}:8001/api/v2/applications/{app_id}", method="POST")
            urllib.request.urlopen(req, timeout=6).read()
        self.jobs.put((job, label))

    def power(self):
        def job():
            if is_on():
                self._key("KEY_POWER")
            else:
                wake()
        self.jobs.put((job, "Liga/desliga"))


def tv_mac_at(ip, timeout=1.5):
    try:
        with urllib.request.urlopen(f"http://{ip}:8001/api/v2/", timeout=timeout) as r:
            return json.load(r).get("device", {}).get("wifiMac", "").upper()
    except Exception:
        return None


def find_tv():
    """The router hands the TV a new IP now and then: if it isn't at TV_IP, scan the subnet for it."""
    global TV_IP
    # while the TV plays the PC-screen stream its API takes ~5 s to answer
    if tv_mac_at(TV_IP, timeout=10) == TV_MAC:
        return
    prefix = TV_IP.rsplit(".", 1)[0]
    found = []

    def probe(ip):
        if tv_mac_at(ip) == TV_MAC:
            found.append(ip)
    threads = [threading.Thread(target=probe, args=(f"{prefix}.{i}",), daemon=True) for i in range(1, 255)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(3)
    if found:
        TV_IP = found[0]
        try:
            with open(LAST_IP_FILE, "w") as f:
                f.write(TV_IP)
        except OSError:
            pass


def is_on():
    try:
        with urllib.request.urlopen(f"http://{TV_IP}:8001/api/v2/", timeout=10) as r:
            return json.load(r).get("device", {}).get("PowerState", "on") == "on"
    except Exception:
        return False


def wake():
    mac = bytes.fromhex(TV_MAC.replace(":", ""))
    packet = b"\xff" * 6 + mac * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            s.sendto(packet, ("255.255.255.255", 9))
            s.sendto(packet, (TV_IP, 9))


def icon_font(size):
    f = QFont("Segoe Fluent Icons")
    f.setPixelSize(size)
    return f


class IconButton(QPushButton):
    def __init__(self, glyph, tip="", size=44, glyph_px=18, color=None, text=None, repeat=False):
        super().__init__()
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRepeat(repeat)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(120)
        bg = color or T["btn"]
        if text:
            self.setText(f"{glyph}  {text}" if glyph else text)
            self.setMinimumHeight(size)
            self.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        else:
            self.setText(glyph)
            self.setFixedSize(size, size)
            self.setFont(icon_font(glyph_px))
        radius = 12 if text else size // 2
        self.setStyleSheet(f"""
            QPushButton {{ background:{bg}; color:{T['fg']}; border:none; border-radius:{radius}px; padding:0 10px; }}
            QPushButton:hover {{ background:{QColor(bg).lighter(125).name()}; }}
            QPushButton:pressed {{ background:{QColor(bg).lighter(150).name()}; }}""")


class DPad(QWidget):
    """Round direction pad: four arc segments around a central OK button."""
    pressed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setFixedSize(214, 214)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover = None
        self.down = None
        self.setMouseTracking(True)
        self.repeat = QTimer(self, interval=120)
        self.repeat.timeout.connect(lambda: self.down and self.down != "KEY_ENTER" and self.pressed.emit(self.down))
        self.delay = QTimer(self, singleShot=True, interval=350)
        self.delay.timeout.connect(self.repeat.start)

    def _zone(self, pos):
        c = QPointF(self.width() / 2, self.height() / 2)
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        r = math.hypot(dx, dy)
        if r > self.width() / 2:
            return None
        if r < 40:
            return "KEY_ENTER"
        ang = math.degrees(math.atan2(-dy, dx)) % 360
        return ("KEY_RIGHT", "KEY_UP", "KEY_LEFT", "KEY_DOWN")[int(((ang + 45) % 360) // 90)]

    def mouseMoveEvent(self, e):
        z = self._zone(e.position())
        if z != self.hover:
            self.hover = z
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        self.down = self._zone(e.position())
        if self.down:
            self.pressed.emit(self.down)
            self.delay.start()
        self.update()

    def mouseReleaseEvent(self, e):
        self.down = None
        self.delay.stop()
        self.repeat.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        c = QPointF(w / 2, w / 2)
        outer = QRectF(2, 2, w - 4, w - 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T["btn"]))
        p.drawEllipse(outer)
        segs = {"KEY_RIGHT": -45, "KEY_UP": 45, "KEY_LEFT": 135, "KEY_DOWN": 225}
        for key, start in segs.items():
            if key in (self.hover, self.down):
                path = QPainterPath(c)
                path.arcTo(outer, start, 90)
                path.closeSubpath()
                p.setBrush(QColor(T["btn_dn"] if key == self.down else T["btn_hi"]))
                p.drawPath(path)
        p.setPen(QPen(QColor(T["bg"]), 3))
        for a in (45, 135, 225, 315):
            rad = math.radians(a)
            p.drawLine(c + QPointF(44 * math.cos(rad), -44 * math.sin(rad)),
                       c + QPointF((w / 2) * math.cos(rad), -(w / 2) * math.sin(rad)))
        p.setPen(QColor(T["fg"]))
        p.setFont(icon_font(18))
        for key, glyph, dx, dy in (("KEY_UP", IC["up"], 0, -76), ("KEY_DOWN", IC["down"], 0, 76),
                                   ("KEY_LEFT", IC["left"], -76, 0), ("KEY_RIGHT", IC["right"], 76, 0)):
            p.drawText(QRectF(c.x() + dx - 16, c.y() + dy - 16, 32, 32), Qt.AlignmentFlag.AlignCenter, glyph)
        ok = "KEY_ENTER"
        p.setPen(QPen(QColor(T["bg"]), 4))
        col = QColor(T["accent"])
        if self.down == ok:
            col = col.lighter(130)
        elif self.hover == ok:
            col = col.lighter(115)
        p.setBrush(col)
        p.drawEllipse(c, 40, 40)
        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        p.drawText(QRectF(c.x() - 40, c.y() - 40, 80, 80), Qt.AlignmentFlag.AlignCenter, "OK")


class Rocker(QFrame):
    """Vertical pill: + on top, label in the middle, - at the bottom (both auto-repeat)."""

    def __init__(self, label, up_glyph, down_glyph, on_up, on_down, mid_glyph=None, on_mid=None):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background:{T['btn']}; border-radius:28px; }}")
        self.setFixedWidth(56)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        up = IconButton(up_glyph, f"{label} +", 48, 18, T["btn"], repeat=True)
        down = IconButton(down_glyph, f"{label} −", 48, 18, T["btn"], repeat=True)
        up.clicked.connect(on_up)
        down.clicked.connect(on_down)
        lay.addWidget(up)
        if mid_glyph:
            mid = IconButton(mid_glyph, "Mudo", 40, 15, T["btn"])
            mid.clicked.connect(on_mid)
            lay.addWidget(mid, alignment=Qt.AlignmentFlag.AlignHCenter)
        else:
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color:{T['dim']}; font: 600 9pt 'Segoe UI'; background:transparent;")
            lbl.setFixedHeight(40)
            lay.addWidget(lbl)
        lay.addWidget(down)


def section(text):
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(f"color:{T['faint']}; font: 700 8pt 'Segoe UI'; letter-spacing:1px; background:transparent;")
    return lbl


class RemoteWindow(QWidget):
    result = pyqtSignal(bool, str)
    status = pyqtSignal(bool, object)

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.remote = Remote(lambda ok, msg: self.result.emit(ok, msg))
        self.result.connect(self.show_result)
        self.status.connect(self.show_status)
        self.setWindowTitle("Controle da TV")
        self.setWindowIcon(self.make_icon())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(f"QWidget {{ background:{T['bg']}; color:{T['fg']}; font-family:'Segoe UI'; }}"
                           f"QToolTip {{ background:{T['card']}; color:{T['fg']}; border:1px solid {T['btn_hi']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(12)
        root.addLayout(self.build_header())
        root.addLayout(self.build_top_row())
        pc = IconButton("", "Mostra a tela 2 do PC no navegador da TV · tecla P", 42, color=T["accent"],
                        text="Tela do PC na TV")
        pc.clicked.connect(self.show_pc_screen)
        stop = IconButton("", "Para a transmissão, fecha o navegador da TV e deixa o PC só no monitor", 42,
                          text="Encerrar")
        stop.clicked.connect(self.stop_pc_screen)
        pc_row = QHBoxLayout()
        pc_row.setSpacing(8)
        pc_row.addWidget(pc, 1)
        pc_row.addWidget(stop)
        root.addLayout(pc_row)
        root.addWidget(self.build_dpad_area(), alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addLayout(self.build_media_row())
        root.addWidget(self.build_text_box())
        root.addWidget(section("Apps"))
        root.addLayout(self.build_apps())
        self.numpad = self.build_numpad()
        self.numpad.setVisible(self.settings.get("numpad", False))
        root.addWidget(self.numpad)
        self.toast = QLabel(" ")
        self.toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast.setStyleSheet(f"color:{T['dim']}; font: 9pt 'Segoe UI';")
        root.addWidget(self.toast)
        hint = QLabel("Setas · Enter · Backspace voltar · Esc sair · +/− volume · roda do mouse = volume · "
                      "M mudo · H início · S fonte · Espaço play · F tela cheia · P tela do PC")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color:{T['faint']}; font: 8pt 'Segoe UI';")
        root.addWidget(hint)

        self.setFixedWidth(370)
        self.set_topmost(self.settings.get("topmost", False))
        self.build_tray()
        self.toast_timer = QTimer(self, singleShot=True, interval=2500)
        self.toast_timer.timeout.connect(lambda: self.toast.setText(" "))
        # one light "are you on?" request every 15 s: asking the TV about each app made it crawl
        self.last_app = None
        self.poll = QTimer(self, interval=15000)
        self.poll.timeout.connect(self.refresh_status)
        self.poll.start()
        self.refresh_status()

    # ---- layout pieces -------------------------------------------------
    def build_header(self):
        h = QHBoxLayout()
        h.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        title = QVBoxLayout()
        title.setSpacing(0)
        name = QLabel("Samsung 55\" Série 8")
        name.setStyleSheet("font: 700 12pt 'Segoe UI';")
        self.state = QLabel("Procurando a TV...")
        self.state.setStyleSheet(f"color:{T['dim']}; font: 9pt 'Segoe UI';")
        title.addWidget(name)
        title.addWidget(self.state)
        self.pin = IconButton(IC["pin"], "Manter por cima das outras janelas", 34, 14, T["card"])
        self.pin.clicked.connect(lambda: self.set_topmost(not self.topmost))
        power = IconButton(IC["power"], "Liga/desliga a TV", 44, 18, T["red"])
        power.clicked.connect(self.remote.power)
        h.addWidget(self.dot)
        h.addLayout(title, 1)
        h.addWidget(self.pin)
        h.addWidget(power)
        return h

    def build_top_row(self):
        h = QHBoxLayout()
        h.setSpacing(8)
        for glyph, text, key in ((IC["source"], "Fonte", "KEY_SOURCE"), (IC["menu"], "Menu", "KEY_MENU"),
                                 (IC["info"], "Info", "KEY_INFO")):
            b = IconButton(glyph, text, 38, text=text)
            b.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            b.setText(text)
            b.clicked.connect(lambda _=False, k=key: self.remote.key(k))
            h.addWidget(b)
        full = IconButton("", "Tela cheia no Smarters (OK duas vezes) · tecla F", 38, color=T["accent"], text="Tela cheia")
        full.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        full.clicked.connect(self.fullscreen)
        h.addWidget(full)
        return h

    def build_dpad_area(self):
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        vol = Rocker("VOL", IC["volup"], IC["voldown"], lambda: self.remote.key("KEY_VOLUP"),
                     lambda: self.remote.key("KEY_VOLDOWN"), IC["mute"], lambda: self.remote.key("KEY_MUTE"))
        ch = Rocker("CH", "", "", lambda: self.remote.key("KEY_CHUP"), lambda: self.remote.key("KEY_CHDOWN"))
        dpad = DPad()
        dpad.pressed.connect(self.remote.key)
        grid.addWidget(vol, 0, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(dpad, 0, 1)
        grid.addWidget(ch, 0, 2, alignment=Qt.AlignmentFlag.AlignVCenter)
        nav = QHBoxLayout()
        nav.setSpacing(18)
        for glyph, tip, key in ((IC["back"], "Voltar", "KEY_RETURN"), (IC["home"], "Início", "KEY_HOME"),
                                (IC["close"], "Sair", "KEY_EXIT")):
            b = IconButton(glyph, tip, 46, 17)
            b.clicked.connect(lambda _=False, k=key: self.remote.key(k))
            nav.addWidget(b)
        grid.addLayout(nav, 1, 0, 1, 3, alignment=Qt.AlignmentFlag.AlignHCenter)
        return box

    def build_media_row(self):
        h = QHBoxLayout()
        h.setSpacing(8)
        for glyph, tip, key in ((IC["rew"], "Voltar rápido", "KEY_REWIND"), (IC["play"], "Play", "KEY_PLAY"),
                                (IC["pause"], "Pausar", "KEY_PAUSE"), (IC["stop"], "Parar", "KEY_STOP"),
                                (IC["ff"], "Avançar rápido", "KEY_FF")):
            b = IconButton(glyph, tip, 40, 15, T["card"])
            b.clicked.connect(lambda _=False, k=key: self.remote.key(k))
            h.addWidget(b)
        h.addStretch()
        num = IconButton(IC["dial"], "Mostrar/ocultar números", 40, 15, T["card"])
        num.clicked.connect(self.toggle_numpad)
        h.addWidget(num)
        return h

    def build_text_box(self):
        box = QFrame()
        box.setStyleSheet(f"QFrame {{ background:{T['card']}; border-radius:12px; }}")
        h = QHBoxLayout(box)
        h.setContentsMargins(12, 4, 4, 4)
        ic = QLabel(IC["keyboard"])
        ic.setFont(icon_font(16))
        ic.setStyleSheet(f"color:{T['dim']}; background:transparent;")
        self.text = QLineEdit()
        self.text.setPlaceholderText("Digitar na TV (abra um campo de texto nela antes)")
        self.text.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.text.setStyleSheet(f"QLineEdit {{ background:transparent; border:none; color:{T['fg']}; font: 10pt 'Segoe UI'; }}")
        self.text.returnPressed.connect(self.send_text)
        send = IconButton(IC["send"], "Enviar texto", 34, 14, T["accent"])
        send.clicked.connect(self.send_text)
        h.addWidget(ic)
        h.addWidget(self.text, 1)
        h.addWidget(send)
        return box

    def build_apps(self):
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (name, app_id, color) in enumerate(APPS):
            b = IconButton("", f"Abrir {name}", 40, color=color, text=name)
            b.clicked.connect(lambda _=False, a=app_id, n=name: self.open_app(a, n))
            grid.addWidget(b, i // 2, i % 2)
        return grid

    def build_numpad(self):
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(40, 0, 40, 0)
        grid.setSpacing(6)
        for i, n in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, None, 0, None]):
            if n is None:
                continue
            b = IconButton("", str(n), 36, text=str(n))
            b.clicked.connect(lambda _=False, n=n: self.remote.key(f"KEY_{n}"))
            grid.addWidget(b, i // 3, i % 3)
        return box

    def build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Controle da TV")
        menu = QMenu()
        for text, fn in (("Mostrar controle", self.show_window), ("Tela do PC na TV", self.show_pc_screen),
                         ("Encerrar tela do PC", self.stop_pc_screen),
                         ("Abrir Smarters", lambda: self.open_app(SMARTERS_MACRO, "Smarters")),
                         ("Volume +", lambda: self.remote.key("KEY_VOLUP")), ("Volume −", lambda: self.remote.key("KEY_VOLDOWN")),
                         ("Mudo", lambda: self.remote.key("KEY_MUTE")), ("Play/Pausar", lambda: self.remote.key("KEY_PLAY")),
                         ("Liga/desliga TV", self.remote.power)):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.addSeparator()
        quit_act = QAction("Fechar", menu)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: r == QSystemTrayIcon.ActivationReason.Trigger and self.show_window())
        self.tray.show()

    def make_icon(self):
        ico = os.path.join(HERE, "icon.ico")
        if os.path.exists(ico):
            return QIcon(ico)
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(T["accent"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        p.setPen(QColor("white"))
        p.setFont(icon_font(32))
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, IC["tv"])
        p.end()
        return QIcon(pm)

    # ---- actions -------------------------------------------------------
    def open_app(self, app_id, name):
        self.last_app = name
        if isinstance(app_id, list):
            self.remote.macro(app_id, f"Abrindo {name}")
        else:
            self.remote.launch(app_id, f"Abrindo {name}")

    def fullscreen(self):
        # in Smarters, OK on the item that is already playing twice hides the side lists
        self.remote.macro(["KEY_ENTER", 0.5, "KEY_ENTER"], "Tela cheia")

    def show_pc_screen(self):
        # tela_dlna manda a tela (com som) pro player da TV por DLNA — sem navegador e sem "Permitir"
        subprocess.Popen([sys.executable, os.path.join(HERE, "tela_dlna.py")], cwd=HERE,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        self.last_app = "Tela do PC"
        self.show_result(True, "Mandando a tela (com som) pra TV…")

    def stop_pc_screen(self):
        subprocess.Popen([sys.executable, os.path.join(HERE, "tela_dlna.py"), "parar"], cwd=HERE,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        self.last_app = None
        self.show_result(True, "Tela do PC encerrada")

    def send_text(self):
        t = self.text.text()
        if t:
            self.remote.text(t)
            self.text.clear()

    def toggle_numpad(self):
        vis = not self.numpad.isVisible()
        self.numpad.setVisible(vis)
        self.settings["numpad"] = vis
        save_settings(self.settings)
        QTimer.singleShot(0, self.adjustSize)

    def set_topmost(self, on):
        self.topmost = on
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.pin.setText(IC["unpin"] if on else IC["pin"])
        self.pin.setToolTip("Soltar janela" if on else "Manter por cima das outras janelas")
        self.settings["topmost"] = on
        save_settings(self.settings)
        self.show()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_result(self, ok, msg):
        self.toast.setStyleSheet(f"color:{T['dim'] if ok else T['red']}; font: 9pt 'Segoe UI';")
        self.toast.setText(msg if not ok else f"✓ {msg}")
        self.toast_timer.start()

    def refresh_status(self):
        def work():
            on = is_on()
            if not on:  # the TV may just have a new IP
                find_tv()
                on = is_on()
            if not on:
                self.last_app = None
            self.status.emit(on, self.last_app)
            self.checking = False
        # a check can outlast the 6 s poll while the TV is slow: don't stack them
        if getattr(self, "checking", False):
            return
        self.checking = True
        threading.Thread(target=work, daemon=True).start()

    def show_status(self, on, app):
        self.dot.setStyleSheet(f"background:{T['green'] if on else T['faint']}; border-radius:5px;")
        if on:
            self.state.setText(f"Ligada · {app}" if app else "Ligada")
        else:
            self.state.setText("Desligada ou fora da rede")

    # ---- input ---------------------------------------------------------
    def keyPressEvent(self, e):
        k = KEYBOARD.get(e.key())
        if e.key() == Qt.Key.Key_F and not self.text.hasFocus():
            self.fullscreen()
        elif e.key() == Qt.Key.Key_P and not self.text.hasFocus():
            self.show_pc_screen()
        elif k and not self.text.hasFocus():
            self.remote.key(k)
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        self.remote.key("KEY_VOLUP" if e.angleDelta().y() > 0 else "KEY_VOLDOWN")

    def mousePressEvent(self, e):
        self.text.clearFocus()
        self.setFocus()
        super().mousePressEvent(e)

    def closeEvent(self, e):
        self.tray.hide()
        super().closeEvent(e)


if __name__ == "__main__":
    # pythonw has no console: keep crashes in a file so they can be looked at later
    import faulthandler
    import traceback
    _log = open(os.path.join(HERE, "erros.log"), "a", encoding="utf-8")
    faulthandler.enable(_log)
    sys.excepthook = lambda *exc: (_log.write(time.strftime("\n[%d/%m %H:%M:%S]\n")),
                                   traceback.print_exception(*exc, file=_log), _log.flush())
    threading.excepthook = lambda a: sys.excepthook(a.exc_type, a.exc_value, a.exc_traceback)
    try:  # own taskbar identity, so Windows shows our icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClaudePC.ControleTV")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("Controle da TV")
    w = RemoteWindow()
    w.show()
    w.setFocus()
    sys.exit(app.exec())
