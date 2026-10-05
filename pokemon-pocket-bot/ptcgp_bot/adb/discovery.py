"""Descoberta automática de emuladores e dispositivos.

Cada emulador expõe ADB em portas previsíveis. Tentamos `adb connect` em todas elas em
paralelo (threads) e devolvemos os seriais que ficaram online. Isso facilita rodar
MuMu + LDPlayer + BlueStacks + celulares Wi-Fi ao mesmo tempo sem configurar nada.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .client import AdbClient

log = logging.getLogger(__name__)

# Portas conhecidas por emulador. Instâncias extras seguem o passo indicado.
KNOWN_EMULATOR_PORTS: dict[str, dict] = {
    "MuMu Player 12": {"base": 16384, "step": 32, "count": 16},
    "MuMu Player (legacy)": {"base": 7555, "step": 1, "count": 1},
    "LDPlayer": {"base": 5555, "step": 2, "count": 16},
    "BlueStacks 5": {"base": 5555, "step": 10, "count": 8},
    "BlueStacks 5 (alt)": {"base": 5565, "step": 10, "count": 8},
    "Nox": {"base": 62001, "step": 24, "count": 8},
    "Nox (alt)": {"base": 62025, "step": 1, "count": 1},
    "MEmu": {"base": 21503, "step": 10, "count": 8},
    "Android Studio AVD": {"base": 5554, "step": 2, "count": 8},
}


@dataclass(frozen=True)
class Candidate:
    address: str
    emulator: str


def discover_candidates(extra_ports: list[int] | None = None,
                        remote_hosts: list[str] | None = None,
                        host: str = "127.0.0.1") -> list[Candidate]:
    """Gera a lista de endereços host:porta a testar (sem duplicatas, ordem estável)."""
    seen: set[str] = set()
    out: list[Candidate] = []

    def add(addr: str, label: str) -> None:
        if addr not in seen:
            seen.add(addr)
            out.append(Candidate(addr, label))

    for name, spec in KNOWN_EMULATOR_PORTS.items():
        for i in range(spec["count"]):
            port = spec["base"] + i * spec["step"]
            add(f"{host}:{port}", name)
    for port in extra_ports or []:
        add(f"{host}:{port}", "extra")
    for remote in remote_hosts or []:
        addr = remote if ":" in remote else f"{remote}:5555"
        add(addr, "remote")
    return out


def discover_devices(client: AdbClient, extra_ports: list[int] | None = None,
                     remote_hosts: list[str] | None = None, connect_timeout: float = 3.0,
                     workers: int = 32) -> list[str]:
    """Conecta em todos os candidatos em paralelo e devolve os seriais online.

    Inclui também dispositivos USB já visíveis em `adb devices`.
    """
    client.start_server()
    candidates = discover_candidates(extra_ports, remote_hosts)
    log.info("Varrendo %d endereços de emuladores/dispositivos...", len(candidates))

    connected: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.connect, c.address, connect_timeout): c for c in candidates}
        for fut in as_completed(futures):
            cand = futures[fut]
            try:
                if fut.result():
                    connected[cand.address] = cand.emulator
            except Exception as exc:  # noqa: BLE001
                log.debug("falha ao conectar %s: %s", cand.address, exc)

    # Remove endereços que responderam ao connect mas não ficaram online (offline/unauthorized).
    online = set(client.online_serials())
    for addr in list(connected):
        if addr not in online:
            client.disconnect(addr)
            connected.pop(addr, None)

    serials = sorted(online)
    for s in serials:
        log.info("  dispositivo online: %s (%s)", s, connected.get(s, "usb/outro"))
    return serials
