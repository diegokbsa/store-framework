"""Detecção da tela atual do jogo a partir de um frame.

Cada estado tem uma lista de templates que o identificam. A ordem de `PRIORITY` importa:
popups de erro são checados primeiro porque sobrepõem qualquer tela.
"""
from __future__ import annotations

from enum import Enum

import numpy as np

from ..vision.matcher import Match, TemplateMatcher


class GameState(str, Enum):
    UNKNOWN = "unknown"
    APP_CLOSED = "app_closed"
    ERROR_POPUP = "error_popup"
    DOWNLOAD_CONFIRM = "download_confirm"
    TITLE = "title"
    AGE_CONFIRM = "age_confirm"
    COUNTRY = "country"
    TERMS = "terms"
    NAME_INPUT = "name_input"
    TUTORIAL = "tutorial"
    TUTORIAL_PACK = "tutorial_pack"
    PACK_SELECT = "pack_select"
    PACK_OPENING = "pack_opening"
    PACK_RESULT = "pack_result"
    HOME = "home"
    ACCOUNT_MENU = "account_menu"
    GENERIC_OK = "generic_ok"
    GENERIC_NEXT = "generic_next"
    GENERIC_SKIP = "generic_skip"


# estado -> templates que o identificam
STATE_TEMPLATES: dict[GameState, list[str]] = {
    GameState.ERROR_POPUP: ["error_popup"],
    GameState.DOWNLOAD_CONFIRM: ["download_confirm"],
    GameState.TITLE: ["title_tap_to_start"],
    GameState.AGE_CONFIRM: ["age_confirm"],
    GameState.COUNTRY: ["country_confirm"],
    GameState.TERMS: ["terms_agree", "terms_checkbox"],
    GameState.NAME_INPUT: ["name_input"],
    GameState.TUTORIAL_PACK: ["tutorial_pack"],
    GameState.PACK_RESULT: ["pack_result_next", "pack_result_ok"],
    GameState.PACK_OPENING: ["pack_swipe_hint", "open_pack_button"],
    GameState.PACK_SELECT: ["pack_select_screen"],
    GameState.HOME: ["home_shop", "wonder_pick"],
    GameState.ACCOUNT_MENU: ["account_menu"],
    GameState.GENERIC_SKIP: ["btn_skip"],
    GameState.GENERIC_NEXT: ["btn_next"],
    GameState.GENERIC_OK: ["btn_ok"],
}

PRIORITY: list[GameState] = [
    GameState.ERROR_POPUP,
    GameState.DOWNLOAD_CONFIRM,
    GameState.TITLE,
    GameState.AGE_CONFIRM,
    GameState.COUNTRY,
    GameState.TERMS,
    GameState.NAME_INPUT,
    GameState.TUTORIAL_PACK,
    GameState.PACK_RESULT,
    GameState.PACK_OPENING,
    GameState.PACK_SELECT,
    GameState.HOME,
    GameState.ACCOUNT_MENU,
    GameState.GENERIC_SKIP,
    GameState.GENERIC_NEXT,
    GameState.GENERIC_OK,
]

# ROIs (x, y, w, h) na referência 540x960 para acelerar o matching dos elementos fixos.
DEFAULT_ROIS: dict[str, tuple[int, int, int, int]] = {
    "title_tap_to_start": (0, 600, 540, 360),
    "btn_ok": (0, 500, 540, 460),
    "btn_next": (0, 600, 540, 360),
    "btn_skip": (300, 0, 240, 200),
    "btn_close": (380, 0, 160, 300),
    "home_shop": (0, 820, 540, 140),
    "wonder_pick": (0, 820, 540, 140),
    "open_pack_button": (0, 650, 540, 310),
    "pack_result_next": (0, 700, 540, 260),
    "pack_result_ok": (0, 700, 540, 260),
    "error_popup": (0, 250, 540, 460),
    "download_confirm": (0, 250, 540, 460),
}


class StateDetector:
    def __init__(self, matcher: TemplateMatcher) -> None:
        self.matcher = matcher
        for name, roi in DEFAULT_ROIS.items():
            matcher.set_roi(name, *roi)

    def detect(self, frame: np.ndarray) -> tuple[GameState, Match | None]:
        for state in PRIORITY:
            m = self.matcher.find_any(frame, STATE_TEMPLATES[state])
            if m:
                return state, m
        return GameState.UNKNOWN, None
