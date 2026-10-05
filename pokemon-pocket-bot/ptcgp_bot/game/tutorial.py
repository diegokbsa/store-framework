"""Fluxo de criação de conta nova + tutorial até a tela Home.

Cada passo é tolerante: se o template da tela esperada não aparece dentro do timeout
curto, o passo é pulado (o jogo às vezes salta telas dependendo da região/versão).
Nomes de jogador são gerados aleatoriamente para evitar repetição.
"""
from __future__ import annotations

import logging
import random
import string
import time

from .actions import GameActions, ScreenTimeout
from .states import GameState

log = logging.getLogger(__name__)

# Coordenadas (referência 540x960) usadas quando não há template específico.
CENTER = (270, 480)
TAP_TO_START = (270, 800)


def random_player_name(prefix: str = "", length: int = 8) -> str:
    alphabet = string.ascii_letters
    body = "".join(random.choice(alphabet) for _ in range(length - len(prefix)))
    return (prefix + body)[:12]


class TutorialFlow:
    def __init__(self, actions: GameActions, skip_animations: bool = True) -> None:
        self.a = actions
        self.skip_animations = skip_animations

    def _step(self, name: str, timeout: float = 12.0, required: bool = False) -> bool:
        try:
            self.a.wait_and_tap(name, timeout=timeout)
            return True
        except ScreenTimeout:
            if required:
                raise
            log.debug("[%s] passo '%s' não apareceu, pulando", self.a.device.label, name)
            return False

    # ---------- passos ----------
    def pass_title(self) -> None:
        """Tela inicial: toque para começar + possível download de dados."""
        try:
            m = self.a.wait_any(["title_tap_to_start", "download_confirm", "btn_ok"], timeout=60)
        except ScreenTimeout:
            # Tenta um toque no centro da parte inferior mesmo sem template.
            self.a.tap_ref(*TAP_TO_START)
            return
        self.a.tap_match(m)
        time.sleep(self.a.base_delay)
        # Download de dados adicionais (primeira abertura após pm clear).
        if self._step("download_confirm", timeout=3):
            self.a.wait_state(GameState.AGE_CONFIRM, GameState.COUNTRY, GameState.TERMS,
                              GameState.GENERIC_OK, GameState.TITLE, timeout=180)

    def pass_region_and_terms(self) -> None:
        # Idade
        if self._step("age_confirm", timeout=10):
            self._step("btn_ok", timeout=5)
        # País
        if self._step("country_confirm", timeout=8):
            self._step("btn_ok", timeout=5)
        # Termos: marca checkboxes e aceita
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            scr = self.a.frame(force=True)
            boxes = self.a.matcher.find_all(scr.image, "terms_checkbox") \
                if self.a.matcher.has_template("terms_checkbox") else []
            for b in boxes:
                self.a.tap_match(b, scr)
                time.sleep(0.15)
            agree = self.a.matcher.find(scr.image, "terms_agree")
            if agree:
                self.a.tap_match(agree, scr)
                time.sleep(self.a.base_delay)
                break
            time.sleep(0.3)
        # Possíveis telas de privacidade/notificação
        for _ in range(3):
            if not (self._step("btn_ok", timeout=3) or self._step("btn_next", timeout=2)):
                break

    def enter_name(self, name: str | None = None) -> str:
        name = name or random_player_name()
        if self._step("name_input", timeout=15):
            time.sleep(0.4)
            self.a.device.text(name)
            time.sleep(0.3)
            self.a.device.key(66)  # ENTER
            time.sleep(self.a.base_delay)
            # Confirmações do nome
            self._step("btn_ok", timeout=5)
            self._step("btn_ok", timeout=3)
        return name

    def skip_tutorial_dialogs(self, max_seconds: float = 90.0) -> None:
        """Avança diálogos do tutorial tocando rápido até aparecer o pacote ou a Home."""
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            st, m = self.a.state()
            if st in (GameState.TUTORIAL_PACK, GameState.PACK_OPENING, GameState.HOME,
                      GameState.PACK_SELECT):
                return
            if st in (GameState.GENERIC_SKIP, GameState.GENERIC_NEXT, GameState.GENERIC_OK) and m:
                self.a.tap_match(m)
                time.sleep(0.2)
                continue
            if st == GameState.ERROR_POPUP:
                self.a.dismiss_popups()
                continue
            # Sem template reconhecido: toca no centro para avançar diálogos.
            if self.skip_animations:
                self.a.spam_tap(*CENTER, times=3, interval=0.1)
            else:
                self.a.tap_ref(*CENTER)
                time.sleep(0.5)
        raise ScreenTimeout(f"[{self.a.device.label}] tutorial não avançou para o pacote")

    def run(self, player_name: str | None = None) -> str:
        """Executa o fluxo completo e retorna o nome usado."""
        log.info("[%s] iniciando tutorial", self.a.device.label)
        self.pass_title()
        self.pass_region_and_terms()
        name = self.enter_name(player_name)
        self.skip_tutorial_dialogs()
        log.info("[%s] tutorial concluído (nome=%s)", self.a.device.label, name)
        return name
