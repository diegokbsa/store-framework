import numpy as np

from ptcgp_bot.vision.matcher import TemplateMatcher


def _screen_with_box(x, y, w=40, h=20, color=(0, 200, 255)):
    scr = np.full((960, 540, 3), 30, dtype=np.uint8)
    scr[y:y + h, x:x + w] = color
    # ruído para evitar matches triviais
    rng = np.random.default_rng(1)
    scr = np.clip(scr.astype(int) + rng.integers(-5, 5, scr.shape), 0, 255).astype(np.uint8)
    return scr


def test_find_returns_center_and_roi_speeds_up():
    scr = _screen_with_box(100, 700)
    tpl = scr[700:720, 100:140].copy()
    m = TemplateMatcher(threshold=0.9)
    m.register("btn", tpl)
    found = m.find(scr, "btn")
    assert found and abs(found.x - 120) <= 1 and abs(found.y - 710) <= 1

    # Fora da ROI não deve encontrar
    assert m.find(scr, "btn", roi=(0, 0, 540, 300)) is None
    m.set_roi("btn", 0, 600, 540, 360)
    assert m.find(scr, "btn") is not None


def test_find_all_counts_distinct_objects():
    scr = np.full((960, 540, 3), 30, dtype=np.uint8)
    for x in (50, 150, 250, 350, 450):
        scr[400:420, x:x + 30] = (255, 255, 255)
    tpl = scr[400:420, 50:80].copy()
    m = TemplateMatcher(threshold=0.95)
    m.register("star", tpl)
    assert len(m.find_all(scr, "star")) == 5


def test_find_any_and_best_of():
    scr = _screen_with_box(200, 200)
    m = TemplateMatcher(threshold=0.9)
    m.register("a", scr[200:220, 200:240].copy())
    m.register("b", np.full((20, 40, 3), 128, dtype=np.uint8))
    assert m.find_any(scr, ["b", "a"]).name == "a"
    assert m.best_of(scr, ["a", "b"]).name == "a"
    assert m.find(scr, "b") is None
