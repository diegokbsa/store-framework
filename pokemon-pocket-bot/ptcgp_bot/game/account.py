"""Backup/restauração e descarte de contas.

O jogo guarda a identidade da conta local em um XML de shared_prefs. Em emuladores com root
conseguimos copiar esse arquivo e, depois, restaurá-lo em qualquer dispositivo para recuperar
a conta que abriu um god pack. Sem root, o fallback é apenas registrar o ID do jogador
(friend code) lido pela tela de perfil, para transferência manual.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass

from ..adb.client import AdbDevice, AdbError

log = logging.getLogger(__name__)


@dataclass
class SavedAccount:
    device: str
    created_at: float
    set_code: str
    rare_count: int
    summary: str
    xml_path: str | None
    screenshot_path: str | None
    player_name: str | None = None
    email: str | None = None
    friend_code: str | None = None


class AccountManager:
    def __init__(self, device: AdbDevice, package: str, accounts_dir: str) -> None:
        self.device = device
        self.package = package
        self.accounts_dir = accounts_dir
        os.makedirs(accounts_dir, exist_ok=True)

    @property
    def prefs_dir(self) -> str:
        return f"/data/data/{self.package}/shared_prefs"

    def list_pref_files(self) -> list[str]:
        out = self.device.shell(f"su -c 'ls {self.prefs_dir}' 2>/dev/null || ls {self.prefs_dir}",
                                check=False)
        return [ln.strip() for ln in out.splitlines() if ln.strip().endswith(".xml")]

    def account_pref_file(self) -> str | None:
        files = self.list_pref_files()
        for f in files:
            if "deviceAccount" in f or "account" in f.lower():
                return f
        return files[0] if files else None

    def backup(self, set_code: str, rare_count: int, summary: str,
               screenshot_path: str | None = None, player_name: str | None = None,
               email: str | None = None) -> SavedAccount:
        ts = int(time.time())
        safe_dev = self.device.serial.replace(":", "_").replace("/", "_")
        base = os.path.join(self.accounts_dir, f"{ts}_{safe_dev}_{set_code}_{rare_count}r")
        xml_path: str | None = None
        pref = self.account_pref_file()
        if pref:
            try:
                data = self.device.su_cat(f"{self.prefs_dir}/{pref}")
                xml_path = base + ".xml"
                with open(xml_path, "wb") as fh:
                    fh.write(data)
                log.info("[%s] backup salvo em %s", self.device.label, xml_path)
            except AdbError as exc:
                log.warning("[%s] sem root para backup do xml: %s", self.device.label, exc)
        else:
            log.warning("[%s] nenhum arquivo de conta encontrado em %s", self.device.label,
                        self.prefs_dir)

        acc = SavedAccount(
            device=self.device.serial, created_at=time.time(), set_code=set_code,
            rare_count=rare_count, summary=summary, xml_path=xml_path,
            screenshot_path=screenshot_path, player_name=player_name, email=email,
        )
        with open(base + ".json", "w", encoding="utf-8") as fh:
            json.dump(asdict(acc), fh, ensure_ascii=False, indent=2)
        return acc

    def restore(self, xml_path: str) -> None:
        """Injeta um backup no dispositivo (app precisa estar fechado)."""
        pref = self.account_pref_file() or "deviceAccount:.xml"
        self.device.stop_app(self.package)
        with open(xml_path, "rb") as fh:
            data = fh.read()
        remote = f"{self.prefs_dir}/{pref}"
        self.device.su_write(remote, data)
        # Ajusta dono do arquivo para o uid do app
        uid = self.device.shell(f"stat -c %u /data/data/{self.package}", check=False).strip()
        if uid.isdigit():
            self.device.shell(f"su -c 'chown {uid}:{uid} {remote}'", check=False)
        log.info("[%s] conta restaurada a partir de %s", self.device.label, xml_path)

    def discard(self, fast: bool = True) -> None:
        """Descarta a conta atual. `fast` usa pm clear (instantâneo)."""
        if fast:
            self.device.stop_app(self.package)
            self.device.clear_app(self.package)
            return
        raise NotImplementedError(
            "exclusão pelo menu do jogo ainda não implementada; use fast_reset=true"
        )
