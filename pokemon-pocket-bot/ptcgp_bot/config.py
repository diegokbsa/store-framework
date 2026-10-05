"""Carregamento e validação de configuração (YAML -> pydantic)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"


class AdbConfig(BaseModel):
    """Opções do cliente ADB."""

    binary: str = "adb"
    server_host: str = "127.0.0.1"
    server_port: int = 5037
    # Portas extras a tentar além das conhecidas dos emuladores.
    extra_ports: list[int] = Field(default_factory=list)
    # Hosts remotos (ex.: celulares com ADB TCP/IP ou outro PC com emuladores).
    remote_hosts: list[str] = Field(default_factory=list)
    connect_timeout: float = 5.0
    auto_discover: bool = True
    # Se true, usa `exec-out screencap -p` (mais rápido). Caso contrário cai em `shell screencap`.
    fast_screencap: bool = True


class DeviceConfig(BaseModel):
    """Configuração por dispositivo (opcional; o pool também descobre sozinho)."""

    serial: str
    name: str | None = None
    enabled: bool = True
    # Escala para templates se o emulador não estiver em 1080x1920 (ou 540x960).
    scale: float | None = None
    # Delay base em segundos para esperar transições de tela neste device.
    base_delay: float = 0.4


class RerollConfig(BaseModel):
    """Parâmetros do loop de reroll."""

    mode: Literal["godpack", "tradeable", "any"] = "godpack"
    # Nº mínimo de cartas raras (2 estrelas+) no pacote para considerar "god pack".
    min_rare_cards: int = 5
    # Expansão alvo (ex.: "A1", "A1a", "A2", "A2a", "A2b", "A3"...). "auto" escolhe a mais nova.
    pack_set: str = "auto"
    # Quantos pacotes abrir por conta antes de descartar (geralmente 1 do tutorial + 1 bônus).
    packs_per_account: int = 2
    # Usa pm clear para resetar a conta (muito mais rápido que a exclusão em jogo).
    fast_reset: bool = True
    # Pula o tutorial via toques rápidos (sem esperar animações terminarem).
    skip_animations: bool = True
    # Polling de tela: intervalo mínimo/máximo adaptativo (segundos).
    poll_min: float = 0.15
    poll_max: float = 1.2
    # Timeout para esperar uma tela esperada antes de tentar recuperação.
    screen_timeout: float = 45.0
    # Após N falhas consecutivas no mesmo device, reinicia o app.
    max_consecutive_failures: int = 3
    # Faz backup da conta encontrada (xml do deviceAccount) via root.
    backup_accounts: bool = True
    # Pasta de saída das contas boas.
    accounts_dir: Path = DATA_DIR / "accounts"
    # Salva screenshot do pacote bom.
    save_screenshots: bool = True
    screenshots_dir: Path = DATA_DIR / "screenshots"
    # Nome do pacote do jogo no Android.
    package_name: str = "jp.pokemon.pokemontcgp"
    # Resolução de referência dos templates.
    reference_resolution: tuple[int, int] = (540, 960)
    # Threshold padrão para template matching (0-1).
    match_threshold: float = 0.86


class EmailConfig(BaseModel):
    """Lista de e-mails e verificação por IMAP."""

    db_path: Path = DATA_DIR / "ptcgp.db"
    # Usa "alias +" (ex.: user+001@gmail.com) a partir de um e-mail base.
    plus_alias_base: str | None = None
    # IMAP para ler códigos de verificação.
    imap_host: str | None = None
    imap_port: int = 993
    imap_user: str | None = None
    imap_password: str | None = None
    imap_folder: str = "INBOX"
    # Padrão regex do código no corpo do e-mail.
    code_regex: str = r"\b(\d{6})\b"
    # Remetente esperado (filtro).
    sender_filter: str = "pokemon"
    # Tempo máximo aguardando o código chegar (segundos).
    wait_timeout: float = 180.0
    poll_interval: float = 5.0


class NotifyConfig(BaseModel):
    discord_webhook: str | None = None
    notify_on_godpack: bool = True
    notify_on_error: bool = True


class DashboardConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8787


class Settings(BaseModel):
    adb: AdbConfig = Field(default_factory=AdbConfig)
    devices: list[DeviceConfig] = Field(default_factory=list)
    reroll: RerollConfig = Field(default_factory=RerollConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    # Nº máximo de devices rodando em paralelo (0 = todos).
    max_parallel_devices: int = 0
    log_level: str = "INFO"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    """Carrega settings.yaml (ou settings.example.yaml como fallback) e devices.yaml.

    Variáveis de ambiente `PTCGP_<SECAO>__<CAMPO>` sobrescrevem valores (ex.:
    PTCGP_EMAIL__IMAP_PASSWORD).
    """
    candidates = []
    if path:
        candidates.append(Path(path))
    candidates += [CONFIG_DIR / "settings.yaml", CONFIG_DIR / "settings.example.yaml"]

    raw: dict = {}
    for cand in candidates:
        if cand.exists():
            with open(cand, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            break

    devices_file = CONFIG_DIR / "devices.yaml"
    if devices_file.exists() and "devices" not in raw:
        with open(devices_file, "r", encoding="utf-8") as fh:
            dev_raw = yaml.safe_load(fh) or {}
        raw["devices"] = dev_raw.get("devices", dev_raw if isinstance(dev_raw, list) else [])

    env_overrides: dict = {}
    for key, value in os.environ.items():
        if not key.startswith("PTCGP_"):
            continue
        parts = key[len("PTCGP_"):].lower().split("__")
        cursor = env_overrides
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    raw = _deep_merge(raw, env_overrides)

    return Settings.model_validate(raw)
