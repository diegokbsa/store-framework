"""Ações de alto nível sobre um dispositivo: esperar tela, tocar em template, etc.

O polling é adaptativo: começa rápido (poll_min) e cresce até poll_max enquanto a tela
não muda, reduzindo screencaps desnecessários sem perder transições rápidas.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from ..adb.client import AdbDevice
from ..config import RerollConfig
from ..vision.matcher import Match, TemplateMatcher
from ..vision.screen import Screen, ScreenGrabber
from .states import GameState, StateDetector

log = logging.getLogger(__name__)


class ScreenTimeout(TimeoutError):
    pass


class GameActions:
    def __init__(self, device: AdbDevice, matcher: TemplateMatcher, cfg: RerollConfig,
                 base_delay: float = 0.4) -> None:
        self.device = device
        self.matcher = matcher
        self.cfg = cfg
        self.base_delay = base_delay
        self.grabber = ScreenGrabber(device, reference=cfg.reference_resolution)
        self.detector = StateDetector(matcher)
        self.last_state: GameState = GameState.UNKNOWN

    # ---------- captura / estado ----------
    def frame(self, force: bool = False) -> Screen:
        return self.grabber.grab(force=force)

    def state(self, force: bool = True) -> tuple[GameState, Match | None]:
        scr = self.frame(force=force)
        st, m = self.detector.detect(scr.image)
        self.last_state = st
        return st, m

    # ---------- toques ----------
    def tap_ref(self, x: int, y: int, screen: Screen | None = None) -> None:
        """Toca em coordenadas da referência (convertendo para a tela real)."""
        scr = screen or self.frame()
        rx, ry = scr.to_real(x, y)
        self.device.tap(rx, ry)

    def tap_match(self, m: Match, screen: Screen | None = None) -> None:
        self.tap_ref(m.x, m.y, screen)

    def tap_template(self, name: str, threshold: float | None = None) -> bool:
        scr = self.frame(force=True)
        m = self.matcher.find(scr.image, name, threshold)
        if not m:
            return False
        self.tap_match(m, scr)
        return True

    def spam_tap(self, x: int, y: int, times: int = 5, interval: float = 0.12) -> None:
        """Toques rápidos para pular animações."""
        scr = self.frame()
        rx, ry = scr.to_real(x, y)
        for _ in range(times):
            self.device.tap(rx, ry)
            time.sleep(interval)

    def swipe_ref(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 250) -> None:
        scr = self.frame()
        a = scr.to_real(x1, y1)
        b = scr.to_real(x2, y2)
        self.device.swipe(*a, *b, duration_ms)

    # ---------- esperas ----------
    def _poll_loop(self, predicate: Callable[[Screen], object], timeout: float,
                   what: str) -> object:
        deadline = time.monotonic() + timeout
        interval = self.cfg.poll_min
        while True:
            scr = self.frame(force=True)
            result = predicate(scr)
            if result:
                return result
            if time.monotonic() >= deadline:
                raise ScreenTimeout(f"[{self.device.label}] timeout esperando {what}")
            time.sleep(interval)
            interval = min(self.cfg.poll_max, interval * 1.5)

    def wait_template(self, name: str, timeout: float | None = None,
                      threshold: float | None = None) -> Match:
        t = timeout if timeout is not None else self.cfg.screen_timeout
        return self._poll_loop(
            lambda s: self.matcher.find(s.image, name, threshold), t, f"template '{name}'"
        )  # type: ignore[return-value]

    def wait_any(self, names: list[str], timeout: float | None = None) -> Match:
        t = timeout if timeout is not None else self.cfg.screen_timeout
        return self._poll_loop(
            lambda s: self.matcher.find_any(s.image, names), t, f"um de {names}"
        )  # type: ignore[return-value]

    def wait_state(self, *states: GameState, timeout: float | None = None) -> GameState:
        t = timeout if timeout is not None else self.cfg.screen_timeout
        wanted = set(states)

        def pred(s: Screen):
            st, _ = self.detector.detect(s.image)
            self.last_state = st
            return st if st in wanted else None

        return self._poll_loop(pred, t, f"estado {[s.value for s in states]}")  # type: ignore[return-value]

    def wait_and_tap(self, name: str, timeout: float | None = None, settle: float | None = None) -> Match:
        m = self.wait_template(name, timeout)
        self.tap_match(m)
        time.sleep(self.base_delay if settle is None else settle)
        return m

    def tap_if_present(self, name: str) -> bool:
        return self.tap_template(name)

    # ---------- app ----------
    def restart_app(self) -> None:
        log.info("[%s] reiniciando o app", self.device.label)
        self.device.stop_app(self.cfg.package_name)
        time.sleep(1.0)
        self.device.start_app(self.cfg.package_name)

    def reset_app_data(self) -> None:
        """Reset instantâneo da conta: apaga os dados do app (equivale a nova conta)."""
        log.info("[%s] pm clear %s", self.device.label, self.cfg.package_name)
        self.device.stop_app(self.cfg.package_name)
        self.device.clear_app(self.cfg.package_name)
        time.sleep(0.5)
        self.device.start_app(self.cfg.package_name)

    def dismiss_popups(self, max_rounds: int = 3) -> int:
        """Fecha popups genéricos (OK / X / erro). Retorna quantos foram fechados."""
        closed = 0
        for _ in range(max_rounds):
            scr = self.frame(force=True)
            m = self.matcher.find_any(scr.image, ["error_popup", "btn_close", "btn_ok"])
            if not m:
                break
            if m.name == "error_popup":
                ok = self.matcher.find(scr.image, "btn_ok")
                if ok:
                    self.tap_match(ok, scr)
                else:
                    self.device.back()
            else:
                self.tap_match(m, scr)
            closed += 1
            time.sleep(self.base_delay)
        return closed
