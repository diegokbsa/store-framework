"""Pool de dispositivos: junta configuração manual + descoberta automática.

Uso:
    pool = DevicePool.from_settings(settings)
    pool.refresh()
    for dev in pool.devices():
        ...
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable

from ..config import DeviceConfig, Settings
from .client import AdbClient, AdbDevice
from .discovery import discover_devices

log = logging.getLogger(__name__)


class DevicePool:
    def __init__(self, client: AdbClient, configured: Iterable[DeviceConfig] = (),
                 auto_discover: bool = True, extra_ports: list[int] | None = None,
                 remote_hosts: list[str] | None = None, connect_timeout: float = 3.0,
                 fast_screencap: bool = True, max_devices: int = 0) -> None:
        self.client = client
        self.configured = {c.serial: c for c in configured}
        self.auto_discover = auto_discover
        self.extra_ports = extra_ports or []
        self.remote_hosts = remote_hosts or []
        self.connect_timeout = connect_timeout
        self.fast_screencap = fast_screencap
        self.max_devices = max_devices
        self._devices: dict[str, AdbDevice] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> "DevicePool":
        client = AdbClient(
            binary=settings.adb.binary,
            host=settings.adb.server_host,
            port=settings.adb.server_port,
        )
        return cls(
            client,
            configured=settings.devices,
            auto_discover=settings.adb.auto_discover,
            extra_ports=settings.adb.extra_ports,
            remote_hosts=settings.adb.remote_hosts,
            connect_timeout=settings.adb.connect_timeout,
            fast_screencap=settings.adb.fast_screencap,
            max_devices=settings.max_parallel_devices,
        )

    # ---------- descoberta ----------
    def refresh(self) -> list[AdbDevice]:
        """Reconecta tudo e atualiza a lista de devices online."""
        serials: list[str] = []

        # 1) dispositivos configurados explicitamente
        for serial, cfg in self.configured.items():
            if not cfg.enabled:
                continue
            if ":" in serial:
                self.client.connect(serial, timeout=self.connect_timeout)
            serials.append(serial)

        # 2) descoberta automática
        if self.auto_discover:
            serials += discover_devices(
                self.client, self.extra_ports, self.remote_hosts, self.connect_timeout
            )
        else:
            serials += self.client.online_serials()

        online = set(self.client.online_serials())
        ordered: list[str] = []
        for s in serials:
            if s in online and s not in ordered:
                cfg = self.configured.get(s)
                if cfg and not cfg.enabled:
                    continue
                ordered.append(s)

        if self.max_devices > 0:
            ordered = ordered[: self.max_devices]

        with self._lock:
            for s in ordered:
                if s not in self._devices:
                    cfg = self.configured.get(s)
                    self._devices[s] = AdbDevice(
                        client=self.client,
                        serial=s,
                        name=cfg.name if cfg else None,
                        fast_screencap=self.fast_screencap,
                    )
            for s in list(self._devices):
                if s not in ordered:
                    del self._devices[s]
        log.info("Pool com %d dispositivo(s): %s", len(ordered), ", ".join(ordered) or "-")
        return self.devices()

    def devices(self) -> list[AdbDevice]:
        with self._lock:
            return list(self._devices.values())

    def get(self, serial: str) -> AdbDevice | None:
        with self._lock:
            return self._devices.get(serial)

    def config_for(self, serial: str) -> DeviceConfig | None:
        return self.configured.get(serial)

    def add_manual(self, address: str, name: str | None = None) -> AdbDevice | None:
        """Conecta um endereço informado pelo usuário (ex.: via dashboard)."""
        if ":" not in address:
            address = f"{address}:5555"
        if not self.client.connect(address, timeout=self.connect_timeout):
            return None
        if address not in self.client.online_serials():
            return None
        dev = AdbDevice(client=self.client, serial=address, name=name,
                        fast_screencap=self.fast_screencap)
        with self._lock:
            self._devices[address] = dev
        return dev

    def remove(self, serial: str) -> None:
        with self._lock:
            self._devices.pop(serial, None)
        if ":" in serial:
            self.client.disconnect(serial)

    def __len__(self) -> int:
        return len(self._devices)
