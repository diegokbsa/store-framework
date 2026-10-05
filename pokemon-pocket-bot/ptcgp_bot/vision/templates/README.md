# Templates

Coloque aqui os recortes (PNG) dos botões/telas do jogo na resolução de referência
**540x960** (ou gere-os com `python -m ptcgp_bot capture <serial>`).

Nomes esperados pelo bot (veja `ptcgp_bot/game/states.py`):

| Arquivo | Tela / elemento |
|---|---|
| `title_tap_to_start.png` | Tela inicial "Toque para começar" |
| `age_confirm.png` | Confirmação de idade |
| `country_confirm.png` | Seleção de país/região |
| `terms_agree.png` | Aceitar termos |
| `terms_checkbox.png` | Checkbox dos termos |
| `btn_ok.png` | Botão OK genérico |
| `btn_next.png` | Botão "Próximo" |
| `btn_skip.png` | Botão "Pular" |
| `btn_close.png` | X de fechar popups |
| `name_input.png` | Campo de nome do jogador |
| `tutorial_pack.png` | Pacote do tutorial |
| `pack_select_*.png` | Capa do booster por expansão (A1, A1a, A2 ...) |
| `open_pack_button.png` | Botão "Abrir" |
| `pack_swipe_hint.png` | Indicador de deslizar o pacote |
| `card_star1.png` ... `card_star3.png` | Ícones de raridade das cartas |
| `card_crown.png` | Ícone de raridade coroa |
| `wonder_pick.png` | Tela de Wonder Pick (home) |
| `home_shop.png` | Ícone da loja (indica tela Home) |
| `account_menu.png` | Menu de conta |
| `delete_account.png` | Botão excluir conta |
| `error_popup.png` | Popup genérico de erro/conexão |
| `download_confirm.png` | Confirmação de download de dados |

Dica: use PNG com fundo transparente para botões sobre fundo animado; a transparência
vira máscara no matching.
