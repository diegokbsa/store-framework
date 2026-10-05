"""Painel web (FastAPI + HTML simples) para acompanhar devices, stats e cadastrar e-mails."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..accounts.email_store import EmailStatus
from ..orchestrator import Orchestrator

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_app(orch: Orchestrator) -> FastAPI:
    app = FastAPI(title="PTCGP Bot")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        snap = orch.snapshot()
        emails = orch.emails.list(limit=200)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "snap": snap,
                "emails": emails,
                "history": orch.emails.verification_history(20),
                "statuses": [s.value for s in EmailStatus],
            },
        )

    # ---------- API ----------
    @app.get("/api/status")
    def api_status():
        return JSONResponse(orch.snapshot())

    @app.post("/api/start")
    def api_start():
        n = orch.start() if not orch.running() else len(orch.workers)
        return {"started": n}

    @app.post("/api/stop")
    def api_stop():
        orch.stop()
        return {"stopped": True}

    @app.post("/api/devices/connect")
    def api_connect(address: str = Form(...), name: str = Form("")):
        ok = orch.add_device(address, name or None)
        return RedirectResponse("/?msg=" + ("conectado" if ok else "falhou"), status_code=303)

    @app.post("/api/devices/scan")
    def api_scan():
        devs = orch.pool.refresh()
        if orch.running():
            for d in devs:
                orch.start_device(d)
        return RedirectResponse(f"/?msg={len(devs)}+dispositivos", status_code=303)

    @app.post("/api/emails/add")
    def api_emails_add(emails: str = Form(...)):
        added, skipped = orch.emails.add_many(emails.replace(",", "\n").splitlines(), note="web")
        return RedirectResponse(f"/?msg=emails+{added}+add+{skipped}+ignorados#emails", status_code=303)

    @app.post("/api/emails/upload")
    async def api_emails_upload(file: UploadFile):
        content = (await file.read()).decode("utf-8", errors="replace")
        added, skipped = orch.emails.add_many(content.splitlines(), note=f"upload:{file.filename}")
        return RedirectResponse(f"/?msg=emails+{added}+add+{skipped}+ignorados#emails", status_code=303)

    @app.post("/api/emails/aliases")
    def api_emails_aliases(base: str = Form(...), count: int = Form(50), start: int = Form(1)):
        try:
            n = orch.emails.generate_aliases(base, count, start)
            msg = f"{n}+aliases"
        except ValueError as exc:
            msg = str(exc).replace(" ", "+")
        return RedirectResponse(f"/?msg={msg}#emails", status_code=303)

    @app.post("/api/emails/{email}/status")
    def api_email_status(email: str, status: str = Form(...)):
        orch.emails.set_status(email, EmailStatus(status))
        return RedirectResponse("/#emails", status_code=303)

    @app.post("/api/emails/{email}/delete")
    def api_email_delete(email: str):
        orch.emails.remove(email)
        return RedirectResponse("/#emails", status_code=303)

    @app.post("/api/emails/release")
    def api_emails_release():
        n = orch.emails.reset_assigned()
        return RedirectResponse(f"/?msg={n}+liberados#emails", status_code=303)

    @app.get("/api/emails")
    def api_emails(status: str | None = None):
        st = EmailStatus(status) if status else None
        return [e.to_dict() for e in orch.emails.list(st)]

    return app


def serve(orch: Orchestrator, host: str = "127.0.0.1", port: int = 8787) -> None:
    import uvicorn

    uvicorn.run(create_app(orch), host=host, port=port, log_level="warning")


def serve_in_thread(orch: Orchestrator, host: str = "127.0.0.1", port: int = 8787) -> threading.Thread:
    t = threading.Thread(target=serve, args=(orch, host, port), daemon=True, name="dashboard")
    t.start()
    return t
