"""Loop de reroll por dispositivo.

Ciclo de uma conta:
  1. reset (pm clear) -> app abre como conta nova
  2. tutorial até a Home
  3. abre N pacotes (tutorial + bônus), avaliando cada um
  4. se bateu o critério (god pack / tradeable), faz backup e notifica
  5. volta ao passo 1

Resiliência: cada ciclo tem timeout; falhas consecutivas reiniciam o app e, se persistirem,
reconectam o ADB. O worker roda em sua própria thread e pode ser parado via `stop_event`.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from ..adb.client import AdbDevice, AdbError
from ..config import RerollConfig
from ..stats import DeviceStats
from ..vision.matcher import TemplateMatcher
from .account import AccountManager, SavedAccount
from .actions import GameActions, ScreenTimeout
from .packs import PackOpener, PackResult
from .states import GameState
from .tutorial import TutorialFlow

log = logging.getLogger(__name__)


@dataclass
class RerollResult:
    packs: list[PackResult]
    saved: SavedAccount | None
    player_name: str
    duration_s: float

    @property
    def best(self) -> PackResult | None:
        return max(self.packs, key=lambda p: p.rare_count) if self.packs else None


class RerollWorker(threading.Thread):
    def __init__(self, device: AdbDevice, cfg: RerollConfig, matcher: TemplateMatcher,
                 stats: DeviceStats, stop_event: threading.Event, base_delay: float = 0.4,
                 on_hit=None, on_error=None, email_provider=None) -> None:
        super().__init__(name=f"reroll-{device.label}", daemon=True)
        self.device = device
        self.cfg = cfg
        self.stats = stats
        self.stop_event = stop_event
        self.on_hit = on_hit
        self.on_error = on_error
        self.email_provider = email_provider  # callable() -> str | None
        self.actions = GameActions(device, matcher, cfg, base_delay=base_delay)
        self.tutorial = TutorialFlow(self.actions, skip_animations=cfg.skip_animations)
        self.packs = PackOpener(
            self.actions, cfg.pack_set, cfg.save_screenshots, str(cfg.screenshots_dir)
        )
        self.accounts = AccountManager(device, cfg.package_name, str(cfg.accounts_dir))
        self.consecutive_failures = 0

    # ---------- critério ----------
    def is_hit(self, result: PackResult) -> bool:
        if self.cfg.mode == "godpack":
            return result.is_god_pack(self.cfg.min_rare_cards)
        if self.cfg.mode == "tradeable":
            return result.is_tradeable_hit()
        return True

    # ---------- um ciclo ----------
    def run_cycle(self) -> RerollResult:
        t0 = time.monotonic()
        self.stats.status = "running"
        self.stats.last_activity = time.time()

        if self.cfg.fast_reset:
            self.actions.reset_app_data()
        else:
            self.actions.restart_app()

        player_name = self.tutorial.run()
        self.stats.accounts += 1

        results: list[PackResult] = []
        saved: SavedAccount | None = None
        for i in range(self.cfg.packs_per_account):
            if self.stop_event.is_set():
                break
            st, _ = self.actions.state()
            if st == GameState.HOME:
                # Vai para a seleção de pacotes (botão central da Home)
                self.actions.tap_ref(270, 480)
                time.sleep(self.actions.base_delay)
            if st in (GameState.PACK_SELECT, GameState.HOME):
                self.packs.select_pack()
            self.packs.open_current_pack(fast=self.cfg.skip_animations)
            result = self.packs.evaluate()
            self.packs.finish_result_screen()
            results.append(result)
            self.stats.packs += 1
            self.stats.last_result = result.summary()
            self.stats.last_activity = time.time()
            log.info("[%s] pacote %d/%d: %s", self.device.label, i + 1,
                     self.cfg.packs_per_account, result.summary())

            if result.is_god_pack(self.cfg.min_rare_cards):
                self.stats.god_packs += 1
            if self.is_hit(result) and saved is None:
                email = self.email_provider() if self.email_provider else None
                if self.cfg.backup_accounts:
                    saved = self.accounts.backup(
                        result.set_code, result.rare_count, result.summary(),
                        result.screenshot_path, player_name, email,
                    )
                self.stats.hits += 1
                if self.on_hit:
                    self.on_hit(self.device, result, saved)
                # Conta boa: não continua abrindo para não arriscar o estado.
                break

        return RerollResult(results, saved, player_name, time.monotonic() - t0)

    # ---------- recuperação ----------
    def recover(self, exc: Exception) -> None:
        self.consecutive_failures += 1
        self.stats.errors += 1
        self.stats.last_error = str(exc)[:200]
        log.warning("[%s] falha %d: %s", self.device.label, self.consecutive_failures, exc)
        if self.on_error:
            self.on_error(self.device, exc)
        try:
            if isinstance(exc, AdbError) or not self.device.is_online():
                self.stats.status = "reconnecting"
                if ":" in self.device.serial:
                    self.device.client.connect(self.device.serial)
                if not self.device.wait_online(timeout=60):
                    time.sleep(10)
                    return
            if self.consecutive_failures >= self.cfg.max_consecutive_failures:
                self.stats.restarts += 1
                self.actions.restart_app()
                self.consecutive_failures = 0
                time.sleep(3)
            else:
                self.actions.dismiss_popups()
        except Exception as inner:  # noqa: BLE001
            log.error("[%s] recuperação falhou: %s", self.device.label, inner)
            time.sleep(5)

    # ---------- thread ----------
    def run(self) -> None:
        log.info("[%s] worker iniciado (modo=%s, set=%s)", self.device.label, self.cfg.mode,
                 self.packs.pack_set)
        while not self.stop_event.is_set():
            try:
                result = self.run_cycle()
                self.consecutive_failures = 0
                self.stats.cycle_times.append(result.duration_s)
                if len(self.stats.cycle_times) > 200:
                    del self.stats.cycle_times[:-200]
            except (ScreenTimeout, AdbError) as exc:
                self.recover(exc)
            except Exception as exc:  # noqa: BLE001
                log.exception("[%s] erro inesperado", self.device.label)
                self.recover(exc)
        self.stats.status = "stopped"
        log.info("[%s] worker finalizado", self.device.label)
