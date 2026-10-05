"""Leitura de códigos de verificação por IMAP.

Suporta caixas com aliases (+tag e pontos do Gmail): o filtro é feito pelo destinatário do
e-mail, então todos os aliases podem apontar para a mesma caixa IMAP.
"""
from __future__ import annotations

import email as email_lib
import imaplib
import logging
import re
import time
from dataclasses import dataclass
from email.header import decode_header

from ..config import EmailConfig

log = logging.getLogger(__name__)


@dataclass
class VerificationCode:
    email: str
    code: str
    subject: str
    received_at: float


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _body_text(msg: email_lib.message.Message) -> str:
    chunks: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload:
                    chunks.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            chunks.append(payload.decode(msg.get_content_charset() or "utf-8", "replace"))
    text = "\n".join(chunks)
    return re.sub(r"<[^>]+>", " ", text)


def extract_code(text: str, pattern: str = r"\b(\d{6})\b") -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


class ImapCodeFetcher:
    def __init__(self, cfg: EmailConfig) -> None:
        self.cfg = cfg
        if not (cfg.imap_host and cfg.imap_user and cfg.imap_password):
            raise ValueError("configure email.imap_host, imap_user e imap_password")

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.cfg.imap_host, self.cfg.imap_port)
        conn.login(self.cfg.imap_user, self.cfg.imap_password)
        conn.select(self.cfg.imap_folder)
        return conn

    def _search_once(self, conn: imaplib.IMAP4_SSL, target: str, since_ts: float) -> VerificationCode | None:
        criteria = ["UNSEEN"]
        if self.cfg.sender_filter:
            criteria += ["FROM", f'"{self.cfg.sender_filter}"']
        typ, data = conn.search(None, *criteria)
        if typ != "OK" or not data or not data[0]:
            return None
        ids = data[0].split()
        for mid in reversed(ids[-30:]):
            typ, msg_data = conn.fetch(mid, "(RFC822)")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email_lib.message_from_bytes(msg_data[0][1])
            to_hdr = (_decode(msg.get("To")) + " " + _decode(msg.get("Delivered-To"))).lower()
            if target and target.lower() not in to_hdr:
                continue
            try:
                ts = email_lib.utils.parsedate_to_datetime(msg.get("Date")).timestamp()
            except Exception:  # noqa: BLE001
                ts = time.time()
            if ts < since_ts - 120:
                continue
            code = extract_code(_decode(msg.get("Subject")) + "\n" + _body_text(msg),
                                self.cfg.code_regex)
            if code:
                conn.store(mid, "+FLAGS", "\\Seen")
                return VerificationCode(target, code, _decode(msg.get("Subject")), ts)
        return None

    def wait_for_code(self, target_email: str, since_ts: float | None = None,
                      timeout: float | None = None) -> VerificationCode | None:
        """Aguarda o e-mail de verificação chegar e devolve o código."""
        since_ts = since_ts or time.time()
        deadline = time.monotonic() + (timeout or self.cfg.wait_timeout)
        conn = self._connect()
        try:
            while time.monotonic() < deadline:
                try:
                    found = self._search_once(conn, target_email, since_ts)
                except imaplib.IMAP4.abort:
                    conn = self._connect()
                    found = None
                if found:
                    log.info("código %s recebido para %s", found.code, target_email)
                    return found
                time.sleep(self.cfg.poll_interval)
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        log.warning("timeout aguardando código para %s", target_email)
        return None
