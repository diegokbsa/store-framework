"""CLI do bot: `python -m ptcgp_bot --help`."""
from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import load_settings

app = typer.Typer(help="PTCGP Bot - reroll para Pokémon TCG Pocket via ADB", no_args_is_help=True)
emails_app = typer.Typer(help="Gerenciar a lista de e-mails para verificação de contas")
devices_app = typer.Typer(help="Gerenciar dispositivos ADB")
app.add_typer(emails_app, name="emails")
app.add_typer(devices_app, name="devices")
console = Console()

_settings_path: str | None = None


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def _settings():
    return load_settings(_settings_path)


@app.callback()
def main(config: str | None = typer.Option(None, "--config", "-c", help="Caminho do settings.yaml"),
         log_level: str | None = typer.Option(None, "--log-level", "-l")):
    global _settings_path
    _settings_path = config
    s = load_settings(config)
    _setup_logging(log_level or s.log_level)


# ---------------- reroll ----------------
@app.command()
def run(dashboard: bool = typer.Option(None, "--dashboard/--no-dashboard",
                                       help="Sobe também o painel web")):
    """Inicia o reroll em todos os dispositivos online."""
    from .orchestrator import Orchestrator

    s = _settings()
    orch = Orchestrator(s)
    use_dash = s.dashboard.enabled if dashboard is None else dashboard
    if use_dash:
        try:
            from .dashboard.server import serve_in_thread

            serve_in_thread(orch, s.dashboard.host, s.dashboard.port)
            console.print(f"[green]Painel:[/] http://{s.dashboard.host}:{s.dashboard.port}")
        except ImportError:
            console.print("[yellow]Dashboard indisponível (pip install fastapi uvicorn jinja2).[/]")
    orch.run_forever()


@app.command()
def dashboard():
    """Sobe apenas o painel web (inicie o reroll pelo botão do painel)."""
    from .dashboard.server import serve
    from .orchestrator import Orchestrator

    s = _settings()
    serve(Orchestrator(s), s.dashboard.host, s.dashboard.port)


@app.command()
def status():
    """Mostra configuração efetiva e dispositivos online."""
    from .adb.device_pool import DevicePool

    s = _settings()
    console.print(f"modo=[bold]{s.reroll.mode}[/] set=[bold]{s.reroll.pack_set}[/] "
                  f"fast_reset={s.reroll.fast_reset} packs/conta={s.reroll.packs_per_account}")
    pool = DevicePool.from_settings(s)
    devs = pool.refresh()
    _print_devices(devs)


def _print_devices(devs) -> None:
    table = Table(title=f"{len(devs)} dispositivo(s) online")
    table.add_column("Serial")
    table.add_column("Nome")
    table.add_column("Modelo")
    table.add_column("Tela")
    table.add_column("Root")
    for d in devs:
        try:
            size = "x".join(map(str, d.screen_size()))
            model = d.model()
            root = "sim" if d.is_rooted() else "não"
        except Exception as exc:  # noqa: BLE001
            size, model, root = "?", f"erro: {exc}", "?"
        table.add_row(d.serial, d.name or "-", model, size, root)
    console.print(table)


# ---------------- devices ----------------
@devices_app.command("scan")
def devices_scan():
    """Varre portas conhecidas de emuladores e lista o que ficou online."""
    from .adb.device_pool import DevicePool

    pool = DevicePool.from_settings(_settings())
    _print_devices(pool.refresh())


@devices_app.command("connect")
def devices_connect(address: str = typer.Argument(..., help="host:porta (ex.: 127.0.0.1:7555)")):
    """Conecta manualmente um endereço ADB."""
    from .adb.client import AdbClient

    s = _settings()
    client = AdbClient(binary=s.adb.binary)
    ok = client.connect(address)
    console.print("[green]conectado[/]" if ok else "[red]falhou[/]")


@devices_app.command("ports")
def devices_ports():
    """Mostra as portas conhecidas por emulador."""
    from .adb.discovery import KNOWN_EMULATOR_PORTS

    table = Table(title="Portas ADB conhecidas")
    table.add_column("Emulador")
    table.add_column("Primeira")
    table.add_column("Passo")
    table.add_column("Instâncias")
    for name, spec in KNOWN_EMULATOR_PORTS.items():
        table.add_row(name, str(spec["base"]), str(spec["step"]), str(spec["count"]))
    console.print(table)


# ---------------- emails ----------------
def _store():
    from .accounts.email_store import EmailStore

    return EmailStore(_settings().email.db_path)


@emails_app.command("add")
def emails_add(emails: list[str] = typer.Argument(..., help="um ou mais e-mails (ou email:senha)")):
    """Cadastra e-mails na lista."""
    added, skipped = _store().add_many(emails)
    console.print(f"adicionados={added} ignorados={skipped}")


@emails_app.command("import")
def emails_import(path: Path = typer.Argument(..., exists=True, help="arquivo .txt, um e-mail por linha")):
    """Importa uma lista de e-mails de um arquivo."""
    added, skipped = _store().import_file(path)
    console.print(f"adicionados={added} ignorados={skipped}")


@emails_app.command("aliases")
def emails_aliases(base: str, count: int = typer.Argument(50), start: int = typer.Option(1)):
    """Gera aliases com '+' (ex.: user+0001@gmail.com) a partir de um e-mail base."""
    n = _store().generate_aliases(base, count, start)
    console.print(f"{n} alias(es) cadastrados")


@emails_app.command("list")
def emails_list(status: str | None = typer.Option(None, "--status", "-s"), limit: int = 100):
    """Lista e-mails cadastrados."""
    from .accounts.email_store import EmailStatus

    store = _store()
    st = EmailStatus(status) if status else None
    table = Table(title="E-mails")
    for col in ("id", "email", "status", "device", "note"):
        table.add_column(col)
    for e in store.list(st, limit=limit):
        table.add_row(str(e.id), e.email, e.status.value, e.device or "-", e.note or "-")
    console.print(table)
    console.print(store.counts())


@emails_app.command("remove")
def emails_remove(email: str):
    """Remove um e-mail."""
    console.print("removido" if _store().remove(email) else "não encontrado")


@emails_app.command("release")
def emails_release(older_than: float = typer.Option(0, help="segundos")):
    """Devolve e-mails reservados (assigned) para disponível."""
    console.print(f"{_store().reset_assigned(older_than)} e-mail(s) liberados")


@emails_app.command("verify")
def emails_verify(email: str, timeout: float = typer.Option(180)):
    """Aguarda e mostra o código de verificação recebido por IMAP para o e-mail."""
    from .accounts.email_store import EmailStatus
    from .accounts.verification import ImapCodeFetcher

    s = _settings()
    store = _store()
    fetcher = ImapCodeFetcher(s.email)
    code = fetcher.wait_for_code(email, timeout=timeout)
    if code:
        store.set_status(email, EmailStatus.VERIFIED)
        store.log_verification(email, code.code, True, code.subject)
        console.print(f"[green]código:[/] {code.code}")
    else:
        store.log_verification(email, None, False, "timeout")
        console.print("[red]código não recebido[/]")
        raise typer.Exit(1)


# ---------------- utilitários ----------------
@app.command()
def capture(serial: str, out: Path = typer.Option(Path("data/screenshots"), "--out", "-o"),
            name: str = typer.Option("capture", "--name", "-n")):
    """Salva um screenshot (na resolução de referência) para recortar templates."""
    from .adb.client import AdbClient
    from .vision.screen import ScreenGrabber

    s = _settings()
    client = AdbClient(binary=s.adb.binary)
    if ":" in serial:
        client.connect(serial)
    dev = client.device(serial, fast_screencap=s.adb.fast_screencap)
    scr = ScreenGrabber(dev, s.reroll.reference_resolution).grab(force=True)
    out.mkdir(parents=True, exist_ok=True)
    import time

    path = out / f"{name}_{int(time.time())}.png"
    scr.save(str(path))
    console.print(f"salvo em {path} (real={scr.real_size}, ref={scr.width}x{scr.height})")


@app.command()
def detect(serial: str):
    """Mostra o estado de tela detectado no dispositivo (para depurar templates)."""
    from .adb.client import AdbClient
    from .game.actions import GameActions
    from .vision.matcher import TemplateMatcher

    s = _settings()
    client = AdbClient(binary=s.adb.binary)
    if ":" in serial:
        client.connect(serial)
    dev = client.device(serial, fast_screencap=s.adb.fast_screencap)
    actions = GameActions(dev, TemplateMatcher(threshold=s.reroll.match_threshold), s.reroll)
    st, m = actions.state()
    console.print(f"estado=[bold]{st.value}[/] match={m}")


@app.command()
def restore(serial: str, xml: Path = typer.Argument(..., exists=True)):
    """Restaura um backup de conta (.xml) em um dispositivo."""
    from .adb.client import AdbClient
    from .game.account import AccountManager

    s = _settings()
    client = AdbClient(binary=s.adb.binary)
    if ":" in serial:
        client.connect(serial)
    dev = client.device(serial)
    AccountManager(dev, s.reroll.package_name, str(s.reroll.accounts_dir)).restore(str(xml))
    dev.start_app(s.reroll.package_name)
    console.print("[green]conta restaurada e app iniciado[/]")


if __name__ == "__main__":
    app()
