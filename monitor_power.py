"""Escurece / restaura o monitor do PC via DDC/CI — SEM atrapalhar a transmissão pra TV.

Importante: NÃO usa "desligar a tela" (DPMS). Desligar a tela pararia o Windows de desenhar e a
transmissão (que captura essa mesma tela) morreria junto. Em vez disso, baixa BRILHO e CONTRASTE a 0
pelo próprio monitor (DDC/CI): o Windows continua desenhando normal, então a TV não é afetada.
Fica bem escuro (não 100% preto — pra isso só com um monitor virtual, que não usamos aqui).

Interruptor: escurece se estiver normal; restaura se estiver escuro.
"""
import ctypes
import json
import os
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "monitor_dark.json")
user32 = ctypes.windll.user32
dxva2 = ctypes.windll.dxva2

VCP_BRIGHTNESS = 0x10
VCP_CONTRAST = 0x12


class PM(ctypes.Structure):
    _fields_ = [("handle", wintypes.HANDLE), ("desc", wintypes.WCHAR * 128)]


def monitors():
    out = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _lprc, _lp):
        n = wintypes.DWORD()
        if dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(n)) and n.value:
            arr = (PM * n.value)()
            if dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, n.value, arr):
                out.extend(pm.handle for pm in arr)
        return True

    user32.EnumDisplayMonitors(0, 0, proc(cb), 0)
    return out


def _get(h, vcp):
    cur, mx = wintypes.DWORD(), wintypes.DWORD()
    if dxva2.GetVCPFeatureAndVCPFeatureReply(h, vcp, None, ctypes.byref(cur), ctypes.byref(mx)):
        return cur.value
    return None


def darken():
    saved = []
    for h in monitors():
        b, c = _get(h, VCP_BRIGHTNESS), _get(h, VCP_CONTRAST)
        saved.append([b, c])
        if b is not None:
            dxva2.SetVCPFeature(h, VCP_BRIGHTNESS, 0)
        if c is not None:
            dxva2.SetVCPFeature(h, VCP_CONTRAST, 0)
    with open(STATE, "w") as f:
        json.dump({"saved": saved}, f)


def restore():
    try:
        with open(STATE) as f:
            saved = json.load(f).get("saved", [])
    except (OSError, ValueError):
        saved = []
    for i, h in enumerate(monitors()):
        b, c = (saved[i] if i < len(saved) else [None, None])
        if b:
            dxva2.SetVCPFeature(h, VCP_BRIGHTNESS, b)
        if c:
            dxva2.SetVCPFeature(h, VCP_CONTRAST, c)
    try:
        os.remove(STATE)
    except OSError:
        pass


def main():
    if os.path.exists(STATE):
        restore()
    else:
        darken()


if __name__ == "__main__":
    main()
