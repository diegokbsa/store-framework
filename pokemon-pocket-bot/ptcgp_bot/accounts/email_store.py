"""Cadastro e controle da lista de e-mails usados para vincular/verificar contas.

Persistência em SQLite (arquivo único, sem servidor). Thread-safe via lock, pois vários
workers podem pedir o "próximo e-mail disponível" ao mesmo tempo.

Estados:
  available -> assigned (reservado por um device) -> used (conta criada)
             -> verified (código confirmado) | failed (descartado)
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailStatus(str, Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    USED = "used"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass
class EmailEntry:
    id: int
    email: str
    status: EmailStatus
    password: str | None
    device: str | None
    account_ref: str | None
    note: str | None
    created_at: float
    updated_at: float

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        return d


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def plus_alias(base: str, index: int, width: int = 4) -> str:
    """meu@gmail.com, 7 -> meu+0007@gmail.com"""
    local, _, domain = base.partition("@")
    local = local.split("+")[0]
    return f"{local}+{index:0{width}d}@{domain}"


class EmailStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'available',
                    password TEXT,
                    device TEXT,
                    account_ref TEXT,
                    note TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status)")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    code TEXT,
                    ok INTEGER NOT NULL,
                    detail TEXT,
                    created_at REAL NOT NULL
                )
                """
            )

    # ---------- escrita ----------
    def add(self, email: str, password: str | None = None, note: str | None = None) -> bool:
        """Adiciona um e-mail. Retorna False se inválido ou duplicado."""
        email = normalize_email(email)
        if not is_valid_email(email):
            return False
        now = time.time()
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO emails(email, status, password, note, created_at, updated_at) "
                    "VALUES (?, 'available', ?, ?, ?, ?)",
                    (email, password, note, now, now),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def add_many(self, emails: Iterable[str], note: str | None = None) -> tuple[int, int]:
        """Retorna (adicionados, ignorados)."""
        added = skipped = 0
        for raw in emails:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # aceita "email" ou "email:senha" / "email,senha"
            password = None
            for sep in (":", ",", ";", "\t"):
                if sep in line:
                    line, password = [p.strip() for p in line.split(sep, 1)]
                    break
            if self.add(line, password, note):
                added += 1
            else:
                skipped += 1
        return added, skipped

    def import_file(self, path: str | Path, note: str | None = None) -> tuple[int, int]:
        with open(path, "r", encoding="utf-8") as fh:
            return self.add_many(fh.readlines(), note or f"import:{Path(path).name}")

    def generate_aliases(self, base: str, count: int, start: int = 1) -> int:
        """Gera e cadastra N aliases com '+' a partir de um e-mail base."""
        base = normalize_email(base)
        if not is_valid_email(base):
            raise ValueError(f"e-mail base inválido: {base}")
        added = 0
        for i in range(start, start + count):
            if self.add(plus_alias(base, i), note="alias"):
                added += 1
        return added

    def remove(self, email: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM emails WHERE email = ?", (normalize_email(email),))
            return cur.rowcount > 0

    def set_status(self, email: str, status: EmailStatus, device: str | None = None,
                   account_ref: str | None = None, note: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE emails SET status = ?, device = COALESCE(?, device), "
                "account_ref = COALESCE(?, account_ref), note = COALESCE(?, note), updated_at = ? "
                "WHERE email = ?",
                (status.value, device, account_ref, note, time.time(), normalize_email(email)),
            )

    def reset_assigned(self, older_than_s: float = 0) -> int:
        """Devolve e-mails 'assigned' para 'available' (ex.: após crash)."""
        cutoff = time.time() - older_than_s
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE emails SET status='available', device=NULL, updated_at=? "
                "WHERE status='assigned' AND updated_at <= ?",
                (time.time(), cutoff),
            )
            return cur.rowcount

    # ---------- leitura ----------
    def _row(self, r: sqlite3.Row) -> EmailEntry:
        return EmailEntry(
            id=r["id"], email=r["email"], status=EmailStatus(r["status"]), password=r["password"],
            device=r["device"], account_ref=r["account_ref"], note=r["note"],
            created_at=r["created_at"], updated_at=r["updated_at"],
        )

    def get(self, email: str) -> EmailEntry | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM emails WHERE email = ?",
                                   (normalize_email(email),)).fetchone()
        return self._row(r) if r else None

    def list(self, status: EmailStatus | None = None, limit: int = 1000,
             offset: int = 0) -> list[EmailEntry]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM emails WHERE status = ? ORDER BY id LIMIT ? OFFSET ?",
                    (status.value, limit, offset),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM emails ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
                ).fetchall()
        return [self._row(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM emails GROUP BY status"
            ).fetchall()
        out = {s.value: 0 for s in EmailStatus}
        for r in rows:
            out[r["status"]] = r["n"]
        out["total"] = sum(out[s.value] for s in EmailStatus)
        return out

    def acquire(self, device: str) -> EmailEntry | None:
        """Reserva atomicamente o próximo e-mail disponível para um device."""
        with self._lock, self._conn:
            r = self._conn.execute(
                "SELECT * FROM emails WHERE status='available' ORDER BY id LIMIT 1"
            ).fetchone()
            if not r:
                return None
            self._conn.execute(
                "UPDATE emails SET status='assigned', device=?, updated_at=? WHERE id=?",
                (device, time.time(), r["id"]),
            )
            r = self._conn.execute("SELECT * FROM emails WHERE id=?", (r["id"],)).fetchone()
        return self._row(r)

    def release(self, email: str) -> None:
        self.set_status(email, EmailStatus.AVAILABLE, device=None)

    # ---------- log de verificação ----------
    def log_verification(self, email: str, code: str | None, ok: bool, detail: str = "") -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO verification_log(email, code, ok, detail, created_at) VALUES (?,?,?,?,?)",
                (normalize_email(email), code, int(ok), detail, time.time()),
            )

    def verification_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM verification_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
