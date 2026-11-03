"""Configuração local da sua TV: MAC e IP.

Fica em `tv_config.json` (ao lado deste arquivo) e NÃO vai para o git — é só seu.
Copie `tv_config.example.json` para `tv_config.json` e ponha o MAC da sua TV Samsung.
O MAC aparece na TV em Configurações › Suporte › Sobre esta TV (endereço MAC do Wi-Fi/LAN),
ou é descoberto sozinho na primeira busca pela rede.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "tv_config.json")
LAST_IP_FILE = os.path.join(HERE, "ultimo_ip.txt")


def _load():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_cfg = _load()


def tv_mac():
    """MAC da TV (para achá-la na rede e para o Wake-on-LAN). Vazio = descobre na busca."""
    return (_cfg.get("mac") or "").upper()


def tv_ip():
    """Último IP conhecido da TV (o roteador troca de vez em quando); senão, o do config; senão, um palpite."""
    try:
        ip = open(LAST_IP_FILE).read().strip()
        if ip:
            return ip
    except OSError:
        pass
    return _cfg.get("ip") or "192.168.1.100"
