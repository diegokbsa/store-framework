
from ptcgp_bot.accounts.verification import extract_code
from ptcgp_bot.config import load_settings


def test_defaults_and_env_override(tmp_path, monkeypatch):
    cfg = tmp_path / "s.yaml"
    cfg.write_text("reroll:\n  mode: tradeable\n  packs_per_account: 3\n", encoding="utf-8")
    monkeypatch.setenv("PTCGP_EMAIL__IMAP_HOST", "imap.test")
    monkeypatch.setenv("PTCGP_REROLL__MIN_RARE_CARDS", "4")
    s = load_settings(cfg)
    assert s.reroll.mode == "tradeable"
    assert s.reroll.packs_per_account == 3
    assert s.reroll.min_rare_cards == 4
    assert s.email.imap_host == "imap.test"
    assert s.reroll.fast_reset is True


def test_extract_code():
    assert extract_code("Seu código de verificação é 482913. Válido por 10 min") == "482913"
    assert extract_code("sem codigo aqui 12345") is None
    assert extract_code("code: AB12CD", r"\b([A-Z0-9]{6})\b") == "AB12CD"
