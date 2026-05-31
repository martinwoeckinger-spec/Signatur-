"""Manueller End-to-End-Demolauf des Mailversands.

Startet einen lokalen Auffang-SMTP-Server, führt den kompletten Workflow aus
(Signaturen -> CRM-Abgleich -> Hinweis) und versendet den Hinweis per SMTP an
diesen Server. Gibt anschließend die tatsächlich empfangene Nachricht aus.

    python scripts/smtp_send_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from smtp_capture_server import SMTPCaptureServer  # noqa: E402

from signatur.crm import get_client  # noqa: E402
from signatur.notifier import build_notification  # noqa: E402
from signatur.pipeline import run_pipeline  # noqa: E402
from signatur.sender import SmtpSender  # noqa: E402


def main() -> int:
    crm = get_client("mock")
    report = run_pipeline(ROOT / "samples", crm)
    draft = build_notification(report, to=["vertrieb@unsere-firma.de"])

    with SMTPCaptureServer() as srv:
        sender = SmtpSender(
            host=srv.host, port=srv.port,
            from_addr="signatur-bot@unsere-firma.de", security="none",
        )
        result = sender.send(draft)
        srv.wait()

    print("=== Versandergebnis ===")
    for k, v in result.items():
        print(f"{k:11}: {v}")
    print("\n=== Vom Server empfangen ===")
    print(f"MAIL FROM : {srv.mail_from}")
    print(f"RCPT TO   : {srv.rcpt_to}")
    # Empfangene Rohnachricht parsen (Betreff/Body sind MIME-kodiert)
    import email
    from email import policy
    parsed = email.message_from_string(srv.data, policy=policy.default)
    decoded_subject = str(parsed["Subject"])
    text_part = parsed.get_body(preferencelist=("plain",))
    text_body = text_part.get_content() if text_part else ""

    print("\n--- Empfangene Header ---")
    for h in ("From", "To", "Subject", "Content-Type"):
        print(f"{h}: {parsed[h]}")
    print("\n--- Entschlüsselter Text-Body (Anfang) ---")
    print("\n".join(text_body.splitlines()[:12]))

    received_ok = (
        result["status"] == "sent"
        and "signatur-bot@unsere-firma.de" in srv.mail_from
        and any("vertrieb@unsere-firma.de" in r for r in srv.rcpt_to)
        and decoded_subject == draft.subject
        and "Anna Berger" in text_body
    )
    print("\nRESULT:", "OK – Mail real versendet & empfangen" if received_ok
          else "FEHLER")
    return 0 if received_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
