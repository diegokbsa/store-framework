"""Notificações (Discord webhook)."""
from __future__ import annotations

import logging
import threading

import requests

from .config import NotifyConfig

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: NotifyConfig) -> None:
        self.cfg = cfg

    def _post(self, content: str, file_path: str | None = None) -> None:
        if not self.cfg.discord_webhook:
            return
        try:
            files = None
            if file_path:
                files = {"file": open(file_path, "rb")}
            requests.post(self.cfg.discord_webhook, data={"content": content}, files=files, timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("falha ao notificar Discord: %s", exc)
        finally:
            if files:
                files["file"].close()

    def send_async(self, content: str, file_path: str | None = None) -> None:
        threading.Thread(target=self._post, args=(content, file_path), daemon=True).start()

    def god_pack(self, device: str, summary: str, screenshot: str | None = None) -> None:
        if self.cfg.notify_on_godpack:
            self.send_async(f"🎉 **GOD PACK** em `{device}` — {summary}", screenshot)

    def hit(self, device: str, summary: str, screenshot: str | None = None) -> None:
        if self.cfg.notify_on_godpack:
            self.send_async(f"✨ Conta salva em `{device}` — {summary}", screenshot)

    def error(self, device: str, message: str) -> None:
        if self.cfg.notify_on_error:
            self.send_async(f"⚠️ `{device}`: {message}")
