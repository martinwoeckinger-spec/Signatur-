"""Versand des Hinweises per SMTP (produktiver Weg neben dem Gmail-Entwurf).

Das Gmail-MCP kann nur Entwürfe anlegen. Für echten Versand – z. B. über das
dedizierte Postfach – nutzt dieser Sender SMTP (Standardbibliothek, ohne
externe Abhängigkeiten). Konfiguration über Umgebungsvariablen:

    SIGNATUR_SMTP_HOST      SMTP-Server (z. B. smtp.gmail.com)
    SIGNATUR_SMTP_PORT      Port (Default: 587 für STARTTLS, 465 für SSL)
    SIGNATUR_SMTP_USER      Login-Benutzer
    SIGNATUR_SMTP_PASSWORD  Login-Passwort / App-Passwort
    SIGNATUR_SMTP_FROM      Absenderadresse (Default: SIGNATUR_SMTP_USER)
    SIGNATUR_SMTP_SECURITY  starttls (Default) | ssl | none
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from .notifier import NotificationDraft


def build_mime(draft: NotificationDraft, from_addr: str) -> EmailMessage:
    """Erzeugt eine MIME-Nachricht (Text + HTML-Alternative) aus dem Draft."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(draft.to)
    msg["Subject"] = draft.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="signatur.local")
    msg.set_content(draft.text or "")
    if draft.html:
        msg.add_alternative(draft.html, subtype="html")
    return msg


class SmtpSender:
    """Versendet einen Hinweis per SMTP."""

    name = "smtp"

    def __init__(
        self,
        host: str = "",
        port: int = 0,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        security: str = "starttls",
        timeout: int = 30,
    ) -> None:
        self.host = host or os.getenv("SIGNATUR_SMTP_HOST", "")
        self.username = username or os.getenv("SIGNATUR_SMTP_USER", "")
        self.password = password or os.getenv("SIGNATUR_SMTP_PASSWORD", "")
        self.security = (
            security or os.getenv("SIGNATUR_SMTP_SECURITY", "starttls")
        ).lower()
        self.from_addr = (
            from_addr or os.getenv("SIGNATUR_SMTP_FROM", "") or self.username
        )
        env_port = os.getenv("SIGNATUR_SMTP_PORT", "")
        self.port = port or (int(env_port) if env_port else 0) or (
            465 if self.security == "ssl" else 587
        )
        self.timeout = timeout
        if not self.host:
            raise ValueError("SMTP: Host fehlt (SIGNATUR_SMTP_HOST).")
        if not self.from_addr:
            raise ValueError("SMTP: Absender fehlt (SIGNATUR_SMTP_FROM/USER).")

    def send(self, draft: NotificationDraft) -> dict[str, Any]:
        msg = build_mime(draft, self.from_addr)
        if self.security == "ssl":
            context = ssl.create_default_context()
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=context
            )
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        try:
            server.ehlo()
            if self.security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if self.username:
                server.login(self.username, self.password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:  # pragma: no cover - Verbindungsabbau best effort
                pass
        return {
            "status": "sent",
            "transport": "smtp",
            "host": self.host,
            "port": self.port,
            "security": self.security,
            "from": self.from_addr,
            "to": draft.to,
            "subject": draft.subject,
            "message_id": msg["Message-ID"],
        }


def get_sender(mode: str = "none", **kwargs) -> SmtpSender | None:
    """Factory: 'smtp' liefert einen SmtpSender, 'none' liefert None (kein Versand)."""
    mode = (mode or "none").lower()
    if mode == "none":
        return None
    if mode == "smtp":
        return SmtpSender(**kwargs)
    raise ValueError(f"Unbekannter Versandmodus: {mode!r} (erlaubt: none, smtp)")
