import numpy as np

from ptcgp_bot.game.packs import PackResult
from ptcgp_bot.game.states import GameState, StateDetector
from ptcgp_bot.vision.matcher import TemplateMatcher


def test_pack_result_criteria():
    r = PackResult("A2", star1=0, star2=3, star3=1, crown=1)
    assert r.rare_count == 5
    assert r.is_god_pack(5)
    assert not PackResult("A2", star1=3, star2=1).is_god_pack(5)
    assert PackResult("A2", star2=1).is_tradeable_hit()
    assert not PackResult("A2", star1=2).is_tradeable_hit()
    assert "3x★★" in r.summary() and "1x♛" in r.summary()
    assert PackResult("A1").summary().endswith("sem raras")


def test_state_detector_priority_error_popup_first():
    scr = np.full((960, 540, 3), 20, dtype=np.uint8)
    scr[300:320, 100:140] = (255, 0, 0)     # "error_popup"
    scr[900:920, 20:60] = (0, 255, 0)       # "home_shop"
    m = TemplateMatcher(threshold=0.95)
    m.register("error_popup", scr[300:320, 100:140].copy())
    m.register("home_shop", scr[900:920, 20:60].copy())
    det = StateDetector(m)
    state, match = det.detect(scr)
    assert state == GameState.ERROR_POPUP and match.name == "error_popup"
    scr[300:320, 100:140] = 20
    state, _ = det.detect(scr)
    assert state == GameState.HOME


def test_state_unknown_without_templates():
    det = StateDetector(TemplateMatcher(threshold=0.95))
    state, match = det.detect(np.zeros((960, 540, 3), dtype=np.uint8))
    assert state == GameState.UNKNOWN and match is None
