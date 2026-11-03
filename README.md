# Controle de TV Samsung pelo PC

Um controle remoto da sua TV **Samsung (Tizen)** rodando no PC: uma janelinha com os botões
(ligar/desligar, volume, setas, trocar canal, abrir apps, digitar texto) que fala com a TV pela
rede Wi-Fi — sem precisar do controle físico. De quebra, manda a **tela do PC para a TV com imagem
e som**.

Feito em Python + PyQt6. Funciona no Windows.

## O que tem

- **Controle remoto da TV** (`controle_tv.pyw`): janela sempre-no-topo opcional, ícone na bandeja,
  atalhos de teclado, busca de canais. Conversa com a TV pelo protocolo da Samsung
  (websocket `:8002` + API REST `:8001`).
- **Tela do PC na TV, com som** (`tela_tv.py`): espelha a tela do PC no navegador da TV via MJPEG,
  e manda o **áudio do sistema** junto (capturado por loopback e recomprimido em MP3 pelo ffmpeg).
  Ótimo pra ver um vídeo/aula do PC na tela grande sem perder o som.

> **Sobre "qualquer TV":** os *botões* do controle são específicos da Samsung (cada marca usa um
> protocolo próprio — LG, Roku, Android TV etc.). Já a parte de **espelhar a tela com som**
> (`tela_tv.py`) é genérica: ela só serve uma página HTTP, então funciona em **qualquer** TV, celular
> ou PC com navegador — é só abrir `http://IP-DO-PC:8090/`.

## Requisitos

- Windows + Python 3.10+
- `pip install -r requirements.txt`
- **ffmpeg** no PATH (só para o som do "tela do PC na TV") — <https://ffmpeg.org>
- A TV e o PC na **mesma rede Wi-Fi**.

## Configuração

1. Copie `tv_config.example.json` para `tv_config.json`.
2. Ponha o **MAC** da sua TV (Samsung: *Configurações › Suporte › Sobre esta TV › endereço MAC*).
   O IP é descoberto sozinho na rede; o campo `ip` é só um palpite inicial.

```json
{"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.100"}
```

Na primeira conexão a TV mostra um aviso **"Permitir"** — aceite. O token de permissão é salvo em
`token.txt` (local, não vai pro git).

## Uso

```sh
python controle_tv.pyw          # abre o controle
python tela_tv.py 8090          # (opcional) só o espelhamento, sem o controle
```

No controle, o botão **"Tela do PC na TV"** liga o espelhamento e abre o navegador da TV apontando
pro PC. Se a TV deixar a imagem muda (política de autoplay), um ENTER pelo controle libera o som.

## Observações

- O sincronismo imagem/som do espelhamento pode ficar levemente defasado — MJPEG não foi feito pra
  isso, mas pra aula/vídeo costuma ficar bom.
- O MAC, o token e o último IP da TV ficam em arquivos locais que **não** são versionados.

## Licença

MIT.
