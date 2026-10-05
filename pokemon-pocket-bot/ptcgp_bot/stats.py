"""Estatísticas thread-safe por dispositivo e globais."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class DeviceStats:
    serial: str
    name: str = ""
    accounts: int = 0
    packs: int = 0
    god_packs: int = 0
    hits: int = 0           # contas salvas (god pack ou tradeable)
    errors: int = 0
    restarts: int = 0
    last_result: str = ""
    last_error: str = ""
    status: str = "idle"
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    cycle_times: list[float] = field(default_factory=list)

    @property
    def avg_cycle_s(self) -> float:
        recent = self.cycle_times[-20:]
        return sum(recent) / len(recent) if recent else 0.0

    @property
    def packs_per_hour(self) -> float:
        elapsed = max(1.0, time.time() - self.started_at)
        return self.packs * 3600.0 / elapsed

    def to_dict(self) -> dict:
        return {
            "serial": self.serial,
            "name": self.name or self.serial,
            "status": self.status,
            "accounts": self.accounts,
            "packs": self.packs,
            "god_packs": self.god_packs,
            "hits": self.hits,
            "errors": self.errors,
            "restarts": self.restarts,
            "avg_cycle_s": round(self.avg_cycle_s, 1),
            "packs_per_hour": round(self.packs_per_hour, 1),
            "last_result": self.last_result,
            "last_error": self.last_error,
            "uptime_s": int(time.time() - self.started_at),
            "idle_s": int(time.time() - self.last_activity),
        }


class StatsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceStats] = {}
        self.started_at = time.time()

    def for_device(self, serial: str, name: str = "") -> DeviceStats:
        with self._lock:
            if serial not in self._devices:
                self._devices[serial] = DeviceStats(serial=serial, name=name)
            return self._devices[serial]

    def remove(self, serial: str) -> None:
        with self._lock:
            self._devices.pop(serial, None)

    def all(self) -> list[DeviceStats]:
        with self._lock:
            return list(self._devices.values())

    def totals(self) -> dict:
        devs = self.all()
        total_packs = sum(d.packs for d in devs)
        total_god = sum(d.god_packs for d in devs)
        elapsed = max(1.0, time.time() - self.started_at)
        return {
            "devices": len(devs),
            "running": sum(1 for d in devs if d.status == "running"),
            "accounts": sum(d.accounts for d in devs),
            "packs": total_packs,
            "god_packs": total_god,
            "hits": sum(d.hits for d in devs),
            "errors": sum(d.errors for d in devs),
            "packs_per_hour": round(total_packs * 3600.0 / elapsed, 1),
            "god_pack_rate": round(100.0 * total_god / total_packs, 3) if total_packs else 0.0,
            "uptime_s": int(elapsed),
        }
