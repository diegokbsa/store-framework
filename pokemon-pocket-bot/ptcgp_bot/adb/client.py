"""Wrapper fino sobre o binário `adb`.

Mantém uma API pequena e previsível:
  - AdbClient: operações do servidor (devices, connect, disconnect).
  - AdbDevice: operações em um dispositivo (shell, tap, swipe, text, screencap, pull...).

Todas as chamadas são síncronas e thread-safe por dispositivo (cada AdbDevice tem seu lock),
o que permite rodar N dispositivos em paralelo com threads.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class AdbError(RuntimeError):
    """Falha ao executar um comando adb."""


@dataclass
class AdbClient:
    binary: str = "adb"
    host: str = "127.0.0.1"
    port: int = 5037
    timeout: float = 30.0

    def __post_init__(self) -> None:
        resolved = shutil.which(self.binary) or self.binary
        self.binary = resolved

    # ---------- utilidades ----------
    def _base_args(self) -> list[str]:
        args = [self.binary]
        if self.host != "127.0.0.1":
            args += ["-H", self.host]
        if self.port != 5037:
            args += ["-P", str(self.port)]
        return args

    def run(self, *args: str, timeout: float | None = None, check: bool = True,
            binary_output: bool = False) -> bytes | str:
        cmd = self._base_args() + list(args)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout or self.timeout,
            )
        except FileNotFoundError as exc:
            raise AdbError(f"adb não encontrado em '{self.binary}'. Instale o platform-tools.") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"timeout executando {' '.join(cmd)}") from exc
        if check and proc.returncode != 0:
            err = proc.stderr.decode(errors="replace").strip()
            raise AdbError(f"adb falhou ({proc.returncode}): {' '.join(args)} -> {err}")
        if binary_output:
            return proc.stdout
        return proc.stdout.decode(errors="replace")

    # ---------- servidor ----------
    def start_server(self) -> None:
        self.run("start-server", check=False)

    def kill_server(self) -> None:
        self.run("kill-server", check=False)

    def devices(self) -> list[tuple[str, str]]:
        """Retorna [(serial, estado)] como em `adb devices`."""
        out = str(self.run("devices"))
        result: list[tuple[str, str]] = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                result.append((parts[0], parts[1]))
        return result

    def online_serials(self) -> list[str]:
        return [s for s, state in self.devices() if state == "device"]

    def connect(self, address: str, timeout: float = 5.0) -> bool:
        """Tenta `adb connect host:port`. Retorna True se conectou."""
        if ":" not in address:
            address = f"{address}:5555"
        try:
            out = str(self.run("connect", address, timeout=timeout, check=False))
        except AdbError as exc:
            log.debug("connect %s falhou: %s", address, exc)
            return False
        ok = "connected" in out.lower() and "cannot" not in out.lower() and "failed" not in out.lower()
        log.debug("connect %s -> %s (%s)", address, ok, out.strip())
        return ok

    def disconnect(self, address: str | None = None) -> None:
        if address:
            self.run("disconnect", address, check=False)
        else:
            self.run("disconnect", check=False)

    def device(self, serial: str, **kwargs) -> "AdbDevice":
        return AdbDevice(client=self, serial=serial, **kwargs)


@dataclass
class AdbDevice:
    client: AdbClient
    serial: str
    name: str | None = None
    fast_screencap: bool = True
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _size_cache: tuple[int, int] | None = field(default=None, repr=False)

    @property
    def label(self) -> str:
        return self.name or self.serial

    # ---------- execução ----------
    def run(self, *args: str, timeout: float | None = None, check: bool = True,
            binary_output: bool = False) -> bytes | str:
        with self._lock:
            return self.client.run("-s", self.serial, *args, timeout=timeout, check=check,
                                   binary_output=binary_output)

    def shell(self, command: str, timeout: float | None = None, check: bool = True) -> str:
        return str(self.run("shell", command, timeout=timeout, check=check))

    def is_online(self) -> bool:
        try:
            return self.shell("echo ok", timeout=5, check=False).strip() == "ok"
        except AdbError:
            return False

    def wait_online(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_online():
                return True
            time.sleep(1.0)
        return False

    # ---------- info ----------
    def screen_size(self, refresh: bool = False) -> tuple[int, int]:
        """(largura, altura) física da tela."""
        if self._size_cache and not refresh:
            return self._size_cache
        out = self.shell("wm size")
        m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(
            r"Physical size:\s*(\d+)x(\d+)", out
        )
        if not m:
            raise AdbError(f"não consegui ler o tamanho de tela de {self.serial}: {out!r}")
        self._size_cache = (int(m.group(1)), int(m.group(2)))
        return self._size_cache

    def prop(self, key: str) -> str:
        return self.shell(f"getprop {key}").strip()

    def model(self) -> str:
        return self.prop("ro.product.model")

    def is_rooted(self) -> bool:
        out = self.shell("su -c id 2>/dev/null || id", check=False)
        return "uid=0" in out

    # ---------- input ----------
    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 200) -> None:
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")

    def long_press(self, x: int, y: int, duration_ms: int = 600) -> None:
        self.swipe(x, y, x, y, duration_ms)

    def key(self, keycode: int | str) -> None:
        self.shell(f"input keyevent {keycode}")

    def back(self) -> None:
        self.key(4)

    def home(self) -> None:
        self.key(3)

    def text(self, value: str) -> None:
        """Digita texto. Escapa espaços e caracteres especiais para `input text`."""
        escaped = (
            value.replace("\\", "\\\\")
            .replace(" ", "%s")
            .replace("&", "\\&")
            .replace("<", "\\<")
            .replace(">", "\\>")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("|", "\\|")
            .replace(";", "\;")
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace("$", "\\$")
        )
        self.shell(f"input text '{escaped}'" if "'" not in value else f'input text "{escaped}"')

    # ---------- tela ----------
    def screencap_png(self) -> bytes:
        """Captura a tela como PNG (bytes)."""
        if self.fast_screencap:
            data = self.run("exec-out", "screencap", "-p", binary_output=True, timeout=15)
            if isinstance(data, bytes) and data[:8] == b"\x89PNG\r\n\x1a\n":
                return data
            log.debug("%s: exec-out screencap inválido, usando fallback shell", self.label)
        data = self.run("shell", "screencap -p", binary_output=True, timeout=20)
        assert isinstance(data, bytes)
        # Alguns devices convertem \n em \r\n no shell; corrige.
        if data[:8] != b"\x89PNG\r\n\x1a\n" and b"\r\n" in data:
            data = data.replace(b"\r\n", b"\n")
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise AdbError(f"screencap retornou dados inválidos em {self.serial}")
        return data

    # ---------- apps ----------
    def start_app(self, package: str, activity: str | None = None) -> None:
        if activity:
            self.shell(f"am start -n {package}/{activity}")
        else:
            self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", check=False)

    def stop_app(self, package: str) -> None:
        self.shell(f"am force-stop {package}", check=False)

    def clear_app(self, package: str) -> None:
        self.shell(f"pm clear {package}")

    def is_app_installed(self, package: str) -> bool:
        return package in self.shell(f"pm list packages {package}", check=False)

    def current_package(self) -> str | None:
        out = self.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", check=False)
        m = re.search(r"([a-zA-Z0-9_.]+)/[a-zA-Z0-9_.]+", out)
        return m.group(1) if m else None

    # ---------- arquivos ----------
    def pull(self, remote: str, local: str) -> None:
        self.run("pull", remote, local, timeout=120)

    def push(self, local: str, remote: str) -> None:
        self.run("push", local, remote, timeout=120)

    def su_cat(self, remote: str) -> bytes:
        """Lê um arquivo como root (emuladores costumam ter su)."""
        for cmd in (f"su -c 'cat {remote}'", f"su 0 cat {remote}", f"cat {remote}"):
            data = self.run("exec-out", cmd, binary_output=True, check=False, timeout=30)
            if isinstance(data, bytes) and data and b"No such file" not in data[:200] \
                    and b"Permission denied" not in data[:200]:
                return data
        raise AdbError(f"não consegui ler {remote} em {self.serial} (sem root?)")

    def su_write(self, remote: str, data: bytes) -> None:
        """Escreve um arquivo como root via push + cp."""
        tmp = f"/data/local/tmp/ptcgp_{int(time.time()*1000)}.tmp"
        import os
        import tempfile

        fd, local_tmp = tempfile.mkstemp(suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            self.push(local_tmp, tmp)
            self.shell(f"su -c 'cp {tmp} {remote} && chmod 660 {remote}' || cp {tmp} {remote}")
            self.shell(f"rm -f {tmp}", check=False)
        finally:
            try:
                os.remove(local_tmp)
            except OSError:
                pass
