"""Apaga a tela do PC sem parar o que vai pra TV.

Usa o "desligar monitor" do Windows (DPMS): o painel apaga de verdade (sem luz na sua cara), mas o
Windows continua desenhando a área de trabalho — então a transmissão da tela pra TV NÃO para.

Pra ligar o monitor de volta é só **mexer o mouse ou apertar uma tecla** (padrão do DPMS).
"""
import ctypes

HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
SMTO_ABORTIFHUNG = 0x0002


def off():
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2, SMTO_ABORTIFHUNG, 3000, None)


if __name__ == "__main__":
    off()
