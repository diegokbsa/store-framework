"""Seleção, abertura e avaliação de pacotes."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .actions import GameActions, ScreenTimeout
from .states import GameState

log = logging.getLogger(__name__)

# Expansões conhecidas (ordem de lançamento). "auto" pega a última da lista que tiver template.
KNOWN_SETS: list[str] = ["A1", "A1a", "A2", "A2a", "A2b", "A3", "A3a", "A3b", "A4", "A4a", "A4b"]

# Posição vertical das 5 cartas na tela de resultado (referência 540x960) e colunas.
# As cartas ficam em leque; usamos regiões para contar ícones de raridade.
RESULT_CARD_REGION = (0, 150, 540, 650)


@dataclass
class PackResult:
    set_code: str
    star1: int = 0
    star2: int = 0
    star3: int = 0
    crown: int = 0
    shiny: int = 0
    screenshot_path: str | None = None
    raw_matches: dict[str, int] = field(default_factory=dict)

    @property
    def rare_count(self) -> int:
        """Cartas 2 estrelas ou melhores (critério usual de god pack)."""
        return self.star2 + self.star3 + self.crown + self.shiny

    @property
    def total_rarity_icons(self) -> int:
        return self.star1 + self.rare_count

    def is_god_pack(self, min_rare: int = 5) -> bool:
        return self.rare_count >= min_rare

    def is_tradeable_hit(self) -> bool:
        """Modo 'tradeable': qualquer carta 2 estrelas+ já vale guardar a conta."""
        return self.rare_count >= 1

    def summary(self) -> str:
        parts = []
        if self.star1:
            parts.append(f"{self.star1}x★")
        if self.star2:
            parts.append(f"{self.star2}x★★")
        if self.star3:
            parts.append(f"{self.star3}x★★★")
        if self.crown:
            parts.append(f"{self.crown}x♛")
        if self.shiny:
            parts.append(f"{self.shiny}x✦")
        return f"[{self.set_code}] " + (" ".join(parts) or "sem raras")


class PackOpener:
    def __init__(self, actions: GameActions, pack_set: str = "auto", save_screenshots: bool = False,
                 screenshots_dir: str | None = None) -> None:
        self.a = actions
        self.pack_set = self.resolve_set(pack_set)
        self.save_screenshots = save_screenshots
        self.screenshots_dir = screenshots_dir

    def resolve_set(self, requested: str) -> str:
        if requested != "auto":
            return requested
        for code in reversed(KNOWN_SETS):
            if self.a.matcher.has_template(f"pack_select_{code}"):
                return code
        return KNOWN_SETS[0]

    # ---------- navegação ----------
    def select_pack(self, timeout: float = 30.0) -> None:
        """Na tela de seleção, desliza até o booster da expansão alvo e confirma."""
        tpl = f"pack_select_{self.pack_set}"
        if not self.a.matcher.has_template(tpl):
            log.warning("[%s] sem template %s; usando o pacote em destaque", self.a.device.label, tpl)
            self.a.tap_ref(270, 480)
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            scr = self.a.frame(force=True)
            m = self.a.matcher.find(scr.image, tpl)
            if m:
                self.a.tap_match(m, scr)
                time.sleep(self.a.base_delay)
                return
            # Desliza a lista de boosters para a direita
            self.a.swipe_ref(430, 480, 110, 480, 300)
            time.sleep(0.6)
        raise ScreenTimeout(f"[{self.a.device.label}] não achei o booster {self.pack_set}")

    def open_current_pack(self, fast: bool = True) -> None:
        """Abre o pacote selecionado: botão abrir, deslizar para rasgar, pular animações."""
        try:
            self.a.wait_and_tap("open_pack_button", timeout=20)
        except ScreenTimeout:
            pass
        # Rasga o pacote (swipe horizontal no topo do booster)
        try:
            self.a.wait_template("pack_swipe_hint", timeout=15)
        except ScreenTimeout:
            pass
        self.a.swipe_ref(80, 430, 460, 430, 200)
        time.sleep(0.8 if fast else 1.5)
        # Pula a animação das cartas
        if fast:
            for _ in range(6):
                self.a.spam_tap(270, 850, times=2, interval=0.08)
                scr = self.a.frame(force=True)
                if self.a.matcher.find_any(scr.image, ["pack_result_next", "pack_result_ok"]):
                    break
                time.sleep(0.25)
        else:
            self.a.wait_any(["pack_result_next", "pack_result_ok"], timeout=40)

    # ---------- avaliação ----------
    def evaluate(self) -> PackResult:
        """Conta ícones de raridade na tela de resultado."""
        scr = self.a.frame(force=True)
        x, y, w, h = RESULT_CARD_REGION
        region = scr.image[y:y + h, x:x + w]
        counts: dict[str, int] = {}
        for name in ("card_star1", "card_star2", "card_star3", "card_crown", "card_shiny"):
            if self.a.matcher.has_template(name):
                counts[name] = len(self.a.matcher.find_all(region, name, threshold=0.88))
        result = PackResult(
            set_code=self.pack_set,
            star1=counts.get("card_star1", 0),
            star2=counts.get("card_star2", 0),
            star3=counts.get("card_star3", 0),
            crown=counts.get("card_crown", 0),
            shiny=counts.get("card_shiny", 0),
            raw_matches=counts,
        )
        if self.save_screenshots and self.screenshots_dir and result.rare_count:
            import os

            os.makedirs(self.screenshots_dir, exist_ok=True)
            fname = f"{int(time.time())}_{self.a.device.label.replace(':', '_')}_{result.rare_count}r.png"
            path = os.path.join(self.screenshots_dir, fname)
            scr.save(path)
            result.screenshot_path = path
        return result

    def finish_result_screen(self) -> None:
        """Sai da tela de resultado de volta para a Home/seleção."""
        for _ in range(4):
            if self.a.tap_if_present("pack_result_next") or self.a.tap_if_present("pack_result_ok"):
                time.sleep(self.a.base_delay)
                continue
            st, m = self.a.state()
            if st in (GameState.HOME, GameState.PACK_SELECT):
                return
            if st in (GameState.GENERIC_OK, GameState.GENERIC_NEXT, GameState.GENERIC_SKIP) and m:
                self.a.tap_match(m)
                time.sleep(self.a.base_delay)
                continue
            self.a.tap_ref(270, 880)
            time.sleep(0.4)
