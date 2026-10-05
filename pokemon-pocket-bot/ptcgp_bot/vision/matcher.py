"""Template matching com OpenCV.

Otimizações para o reroll:
  * templates carregados uma vez e cacheados em memória (por nome);
  * busca restrita a uma região (ROI) quando o botão tem posição conhecida,
    o que reduz o custo em >10x comparado a procurar na tela inteira;
  * suporte a máscara alpha (PNG com transparência) para botões com fundo variável;
  * `find_any` para testar vários templates de uma vez no mesmo frame.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class Match:
    name: str
    x: int          # centro X (coordenadas de referência)
    y: int          # centro Y
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x, self.y


@dataclass
class _Template:
    name: str
    image: np.ndarray
    mask: np.ndarray | None
    roi: tuple[int, int, int, int] | None  # x, y, w, h


class TemplateMatcher:
    def __init__(self, templates_dir: Path | str = TEMPLATES_DIR, threshold: float = 0.86) -> None:
        self.templates_dir = Path(templates_dir)
        self.threshold = threshold
        self._cache: dict[str, _Template] = {}
        self._rois: dict[str, tuple[int, int, int, int]] = {}

    # ---------- carga ----------
    def set_roi(self, name: str, x: int, y: int, w: int, h: int) -> None:
        """Define a região onde um template costuma aparecer (acelera a busca)."""
        self._rois[name] = (x, y, w, h)
        if name in self._cache:
            self._cache[name].roi = self._rois[name]

    def has_template(self, name: str) -> bool:
        return (self.templates_dir / f"{name}.png").exists()

    def load(self, name: str) -> _Template:
        if name in self._cache:
            return self._cache[name]
        path = self.templates_dir / f"{name}.png"
        if not path.exists():
            raise FileNotFoundError(f"template '{name}' não encontrado em {path}")
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise ValueError(f"não consegui ler o template {path}")
        mask = None
        if raw.ndim == 3 and raw.shape[2] == 4:
            alpha = raw[:, :, 3]
            if (alpha < 255).any():
                mask = cv2.merge([alpha, alpha, alpha])
            raw = raw[:, :, :3]
        elif raw.ndim == 2:
            raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
        tpl = _Template(name=name, image=raw, mask=mask, roi=self._rois.get(name))
        self._cache[name] = tpl
        return tpl

    def register(self, name: str, image: np.ndarray,
                 roi: tuple[int, int, int, int] | None = None) -> None:
        """Registra um template vindo de memória (útil em testes/captura)."""
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        self._cache[name] = _Template(name=name, image=image[:, :, :3].copy(), mask=None, roi=roi)

    # ---------- busca ----------
    def find(self, screen: np.ndarray, name: str, threshold: float | None = None,
             roi: tuple[int, int, int, int] | None = None) -> Match | None:
        tpl = self.load(name)
        thr = self.threshold if threshold is None else threshold
        region = roi or tpl.roi
        ox = oy = 0
        haystack = screen
        if region:
            x, y, w, h = region
            x, y = max(0, x), max(0, y)
            haystack = screen[y:y + h, x:x + w]
            ox, oy = x, y
        th, tw = tpl.image.shape[:2]
        if haystack.shape[0] < th or haystack.shape[1] < tw:
            return None
        method = cv2.TM_CCOEFF_NORMED
        if tpl.mask is not None:
            res = cv2.matchTemplate(haystack, tpl.image, cv2.TM_CCORR_NORMED, mask=tpl.mask)
        else:
            res = cv2.matchTemplate(haystack, tpl.image, method)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < thr:
            return None
        cx = ox + max_loc[0] + tw // 2
        cy = oy + max_loc[1] + th // 2
        return Match(name=name, x=cx, y=cy, w=tw, h=th, score=float(max_val))

    def find_all(self, screen: np.ndarray, name: str, threshold: float | None = None,
                 max_results: int = 20) -> list[Match]:
        """Todas as ocorrências (com supressão de vizinhos) — ex.: contar cartas raras."""
        tpl = self.load(name)
        thr = self.threshold if threshold is None else threshold
        th, tw = tpl.image.shape[:2]
        if screen.shape[0] < th or screen.shape[1] < tw:
            return []
        res = cv2.matchTemplate(screen, tpl.image, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=0.0)
        matches: list[Match] = []
        work = res.copy()
        for _ in range(max_results):
            _, max_val, _, max_loc = cv2.minMaxLoc(work)
            if max_val < thr:
                break
            x, y = max_loc
            matches.append(Match(name, x + tw // 2, y + th // 2, tw, th, float(max_val)))
            # Suprime a vizinhança para não contar o mesmo objeto duas vezes.
            x0, y0 = max(0, x - tw // 2), max(0, y - th // 2)
            work[y0:y + th // 2 + 1, x0:x + tw // 2 + 1] = 0
        return matches

    def find_any(self, screen: np.ndarray, names: list[str],
                 threshold: float | None = None) -> Match | None:
        """Primeiro template (na ordem dada) encontrado no frame."""
        for name in names:
            if not self.has_template(name) and name not in self._cache:
                continue
            m = self.find(screen, name, threshold)
            if m:
                return m
        return None

    def best_of(self, screen: np.ndarray, names: list[str],
                threshold: float | None = None) -> Match | None:
        """Entre vários templates, o de maior score (desempate entre telas parecidas)."""
        best: Match | None = None
        for name in names:
            if not self.has_template(name) and name not in self._cache:
                continue
            m = self.find(screen, name, threshold)
            if m and (best is None or m.score > best.score):
                best = m
        return best


def pixel_color(screen: np.ndarray, x: int, y: int) -> tuple[int, int, int]:
    """Cor (R, G, B) de um pixel na referência."""
    b, g, r = screen[y, x]
    return int(r), int(g), int(b)


def color_close(c1: tuple[int, int, int], c2: tuple[int, int, int], tol: int = 25) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))
