"""Orquestra N workers de reroll (um por dispositivo) e o ciclo de vida do bot."""
from __future__ import annotations

import logging
import threading
import time

from .accounts.email_store import EmailStatus, EmailStore
from .adb.client import AdbDevice
from .adb.device_pool import DevicePool
from .config import Settings
from .game.reroll import RerollWorker
from .notify import Notifier
from .stats import StatsRegistry
from .vision.matcher import TemplateMatcher

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool = DevicePool.from_settings(settings)
        self.matcher = TemplateMatcher(threshold=settings.reroll.match_threshold)
        self.stats = StatsRegistry()
        self.notifier = Notifier(settings.notify)
        self.emails = EmailStore(settings.email.db_path)
        self.stop_event = threading.Event()
        self.workers: dict[str, RerollWorker] = {}
        self._lock = threading.Lock()
        self.started_at: float | None = None

    # ---------- callbacks ----------
    def _on_hit(self, device: AdbDevice, result, saved) -> None:
        summary = result.summary()
        if saved and saved.email:
            self.emails.set_status(saved.email, EmailStatus.USED, device=device.serial,
                                   account_ref=saved.xml_path or "")
        if result.is_god_pack(self.settings.reroll.min_rare_cards):
            log.info("🎉 [%s] GOD PACK: %s", device.label, summary)
            self.notifier.god_pack(device.label, summary, result.screenshot_path)
        else:
            self.notifier.hit(device.label, summary, result.screenshot_path)

    def _on_error(self, device: AdbDevice, exc: Exception) -> None:
        self.notifier.error(device.label, str(exc)[:300])

    def _email_provider_for(self, device: AdbDevice):
        def provide() -> str | None:
            entry = self.emails.acquire(device.serial)
            return entry.email if entry else None
        return provide

    # ---------- controle ----------
    def start_device(self, device: AdbDevice) -> RerollWorker | None:
        with self._lock:
            if device.serial in self.workers and self.workers[device.serial].is_alive():
                return self.workers[device.serial]
            cfg = self.pool.config_for(device.serial)
            stats = self.stats.for_device(device.serial, device.name or "")
            worker = RerollWorker(
                device=device,
                cfg=self.settings.reroll,
                matcher=self.matcher,
                stats=stats,
                stop_event=self.stop_event,
                base_delay=cfg.base_delay if cfg else 0.4,
                on_hit=self._on_hit,
                on_error=self._on_error,
                email_provider=self._email_provider_for(device),
            )
            self.workers[device.serial] = worker
            worker.start()
            return worker

    def start(self) -> int:
        self.stop_event.clear()
        self.started_at = time.time()
        devices = self.pool.refresh()
        if not devices:
            log.error("Nenhum dispositivo ADB online. Abra os emuladores ou configure devices.yaml.")
            return 0
        for dev in devices:
            self.start_device(dev)
        log.info("%d worker(s) iniciados", len(self.workers))
        return len(self.workers)

    def add_device(self, address: str, name: str | None = None) -> bool:
        dev = self.pool.add_manual(address, name)
        if not dev:
            return False
        if self.started_at and not self.stop_event.is_set():
            self.start_device(dev)
        return True

    def stop(self, join_timeout: float = 15.0) -> None:
        self.stop_event.set()
        for w in list(self.workers.values()):
            w.join(timeout=join_timeout)
        self.workers.clear()
        log.info("todos os workers parados")

    def running(self) -> bool:
        return any(w.is_alive() for w in self.workers.values())

    def snapshot(self) -> dict:
        return {
            "running": self.running(),
            "totals": self.stats.totals(),
            "devices": [d.to_dict() for d in self.stats.all()],
            "emails": self.emails.counts(),
            "mode": self.settings.reroll.mode,
            "pack_set": self.settings.reroll.pack_set,
        }

    def run_forever(self) -> None:
        """Modo CLI: inicia e fica monitorando até Ctrl+C."""
        n = self.start()
        if not n:
            return
        try:
            while True:
                time.sleep(30)
                t = self.stats.totals()
                log.info("📊 packs=%d god=%d hits=%d %.1f packs/h (%d devices)",
                         t["packs"], t["god_packs"], t["hits"], t["packs_per_hour"], t["devices"])
                # Reinicia workers mortos
                for serial, w in list(self.workers.items()):
                    if not w.is_alive() and not self.stop_event.is_set():
                        dev = self.pool.get(serial)
                        if dev:
                            log.warning("[%s] worker morreu, reiniciando", serial)
                            self.workers.pop(serial)
                            self.start_device(dev)
        except KeyboardInterrupt:
            log.info("Ctrl+C recebido, parando...")
            self.stop()
