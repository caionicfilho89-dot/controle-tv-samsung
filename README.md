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
- **Tela do PC na TV, com som** (`tela_dlna.py`): manda a tela do PC (com o **áudio do sistema**)
  pro player da TV por **DLNA** — o mesmo jeito que apps de mídia enviam filme. A tela é capturada
  pelo ffmpeg (H.264) e o som pelo loopback do alto-falante, juntos num MPEG-TS ao vivo. Ótimo pra
  ver um vídeo/aula do PC na telona sem perder o som. **Não usa o navegador da TV nem pede
  "Permitir"** — importante pra quem não tem o controle físico pra aceitar o aviso.

> **Sobre "qualquer TV":** os *botões* do controle são específicos da Samsung (cada marca usa um
> protocolo próprio — LG, Roku, Android TV etc.). Já a parte de **mandar a tela com som**
> (`tela_dlna.py`) usa DLNA/UPnP, que a maioria das TVs (e caixas de mídia) entende.

## Requisitos

- Windows + Python 3.10+
- `pip install -r requirements.txt`
- **ffmpeg** no PATH (para capturar/enviar a tela com som) — <https://ffmpeg.org>
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
python tela_dlna.py             # (opcional) só manda a tela pra TV; "python tela_dlna.py parar" desliga
```

No controle, o botão **"Tela do PC na TV"** acha a TV na rede e começa a transmitir a tela com som
em poucos segundos; **"Encerrar tela do PC"** desliga. Ele espelha o monitor principal.

## Observações

- Por ser DLNA, a TV costuma bufferizar: a tela pode aparecer com alguns segundos de atraso. Ótimo
  pra assistir vídeo/aula; não serve pra jogo ou coisa que precise de reação imediata.
- O MAC, o token e o último IP da TV ficam em arquivos locais que **não** são versionados.

## Licença

MIT.
