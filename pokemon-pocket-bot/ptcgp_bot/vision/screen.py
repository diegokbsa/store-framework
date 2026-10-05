"""Captura de tela e normalização para a resolução de referência."""
from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..adb.client import AdbDevice

log = logging.getLogger(__name__)


@dataclass
class Screen:
    """Um frame capturado, já em BGR (OpenCV) e redimensionado para a referência."""

    image: np.ndarray  # HxWx3 BGR
    captured_at: float
    scale: float       # fator aplicado (ref / real)
    real_size: tuple[int, int]

    @property
    def width(self) -> int:
        return self.image.shape[1]

    @property
    def height(self) -> int:
        return self.image.shape[0]

    def to_real(self, x: int, y: int) -> tuple[int, int]:
        """Converte coordenadas da referência para a tela real do dispositivo."""
        return int(round(x / self.scale)), int(round(y / self.scale))

    def crop(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        return self.image[y:y + h, x:x + w]

    def save(self, path: str) -> None:
        Image.fromarray(self.image[:, :, ::-1]).save(path)


class ScreenGrabber:
    """Captura frames de um AdbDevice com cache curto para evitar screencaps redundantes."""

    def __init__(self, device: AdbDevice, reference: tuple[int, int] = (540, 960),
                 cache_ttl: float = 0.08) -> None:
        self.device = device
        self.reference = reference
        self.cache_ttl = cache_ttl
        self._last: Screen | None = None
        self.capture_count = 0
        self.total_capture_time = 0.0

    def grab(self, force: bool = False) -> Screen:
        now = time.monotonic()
        if not force and self._last and now - self._last.captured_at < self.cache_ttl:
            return self._last
        t0 = time.perf_counter()
        png = self.device.screencap_png()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        real_w, real_h = img.size
        ref_w, ref_h = self.reference
        # Mantém proporção pela largura (o jogo é portrait fixo).
        scale = ref_w / real_w
        if abs(scale - 1.0) > 1e-3:
            img = img.resize((ref_w, int(round(real_h * scale))), Image.BILINEAR)
        arr = np.asarray(img)[:, :, ::-1].copy()  # RGB -> BGR
        self.capture_count += 1
        self.total_capture_time += time.perf_counter() - t0
        self._last = Screen(image=arr, captured_at=now, scale=scale, real_size=(real_w, real_h))
        return self._last

    @property
    def avg_capture_ms(self) -> float:
        if not self.capture_count:
            return 0.0
        return 1000.0 * self.total_capture_time / self.capture_count
