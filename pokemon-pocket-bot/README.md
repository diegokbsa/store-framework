# PTCGP Bot — reroll para Pokémon TCG Pocket via ADB

Bot em Python que automatiza o reroll de contas no Pokémon TCG Pocket em **vários emuladores /
dispositivos ao mesmo tempo**, procurando god packs (ou cartas trocáveis), salvando o backup da
conta e notificando no Discord. Inclui um **painel web** para acompanhar os dispositivos e
**cadastrar a lista de e-mails** usada na verificação das contas.

> Uso por conta e risco. Automação viola os termos de uso do jogo.

## Principais recursos

- **ADB multi-dispositivo**: descobre sozinho MuMu, LDPlayer, BlueStacks, Nox, MEmu, AVD e
  celulares via Wi-Fi (`adb connect` em paralelo nas portas conhecidas), além de lista fixa em
  `config/devices.yaml`. Um worker (thread) por dispositivo.
- **Reroll otimizado**:
  - reset instantâneo da conta com `pm clear` (sem passar pelo menu de excluir conta);
  - screencap via `exec-out` com cache curto e redimensionamento para resolução de referência;
  - template matching restrito a regiões (ROI), polling adaptativo e skip de animações;
  - recuperação automática (popups, reinício do app, reconexão ADB) e watchdog de workers.
- **Avaliação de pacotes**: conta ícones de raridade (★★, ★★★, coroa, shiny); modos `godpack`,
  `tradeable` e `any`.
- **Backup de contas**: copia o XML de `shared_prefs` (emulador com root) + JSON de metadados +
  screenshot; comando `restore` para injetar a conta em outro dispositivo.
- **Lista de e-mails**: SQLite com estados `available → assigned → used → verified/failed`,
  importação de arquivo, geração de aliases `+0001`, reserva atômica entre workers e leitura do
  código de verificação por **IMAP**.
- **Painel web** (FastAPI): iniciar/parar, re-escanear, conectar ADB manualmente, KPIs por device,
  cadastro/importação de e-mails, troca de status e histórico de verificações.
- **Notificações** no Discord (god pack, conta salva, erro).

## Instalação

```bash
cd pokemon-pocket-bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt                      # ou: pip install -e ".[dashboard]"
cp config/settings.example.yaml config/settings.yaml
```

Requer o `adb` (Android platform-tools) no PATH ou em `adb.binary` no settings.

## Uso rápido

```bash
python -m ptcgp_bot devices scan          # descobre emuladores/dispositivos online
python -m ptcgp_bot devices connect 192.168.0.42:5555
python -m ptcgp_bot status                # config efetiva + tabela de devices (tela, root)

python -m ptcgp_bot emails import data/emails.txt
python -m ptcgp_bot emails aliases meu@gmail.com 100      # meu+0001@gmail.com ... meu+0100
python -m ptcgp_bot emails list --status available
python -m ptcgp_bot emails verify meu+0001@gmail.com      # espera o código por IMAP

python -m ptcgp_bot run                   # reroll em todos os devices + painel em :8787
python -m ptcgp_bot dashboard             # só o painel (inicie pelo botão)
```

Painel: <http://127.0.0.1:8787>

## Templates

O bot reconhece as telas por template matching. Os PNGs ficam em `ptcgp_bot/vision/templates/`
(lista completa em `ptcgp_bot/vision/templates/README.md`) na resolução de referência 540x960.
Para gerar os seus:

```bash
python -m ptcgp_bot capture 127.0.0.1:7555 -n home          # salva data/screenshots/home_*.png
python scripts/crop_template.py data/screenshots/home_123.png home_shop 20 880 60 50
python -m ptcgp_bot detect 127.0.0.1:7555                   # mostra o estado detectado
```

Use PNG com transparência para botões sobre fundo animado (a alfa vira máscara).

## Configuração

`config/settings.yaml` (veja o `.example` comentado). Qualquer campo pode ser sobrescrito por
variável de ambiente `PTCGP_<SECAO>__<CAMPO>`, ex.: `PTCGP_EMAIL__IMAP_PASSWORD=...`.

Seções:

| Seção | Para quê |
|---|---|
| `adb` | binário, portas extras, hosts remotos, screencap rápido |
| `devices` | lista fixa (serial, apelido, enabled, scale, base_delay) |
| `reroll` | modo, set alvo, pacotes por conta, fast_reset, polling, timeouts, backup |
| `email` | banco SQLite, alias base, IMAP para códigos de verificação |
| `notify` | webhook do Discord |
| `dashboard` | host/porta do painel |

## Estrutura

```
ptcgp_bot/
  adb/          cliente adb, descoberta de portas, pool de dispositivos
  vision/       captura de tela, template matcher (ROI, máscara, flat-safe)
  game/         estados, ações, tutorial, pacotes, contas, worker de reroll
  accounts/     lista de e-mails (SQLite) e verificação IMAP
  dashboard/    painel web FastAPI + template HTML
  orchestrator  um worker por device, stats, notificações
  __main__      CLI (typer)
scripts/        adb_connect_all.{sh,bat}, crop_template.py
tests/          pytest (descoberta, e-mails, matcher, estados, config)
```

## Desenvolvimento

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

## Roadmap

- [ ] Exclusão de conta pelo menu do jogo (fallback sem root / sem `pm clear`)
- [ ] Fluxo de vínculo de e-mail dentro do jogo usando a lista + código IMAP
- [ ] OCR do friend code na tela de perfil (`rapidocr`)
- [ ] Wonder Pick automático para contas salvas
- [ ] Empacotar como executável (PyInstaller)
