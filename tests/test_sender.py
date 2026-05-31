"""End-to-End-Test des SMTP-Versands gegen einen lokalen Auffang-Server."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smtp_capture_server import SMTPCaptureServer

from signatur.notifier import NotificationDraft
from signatur.sender import SmtpSender, build_mime


def _draft():
    return NotificationDraft(
        to=["empfaenger@example.com"],
        subject="[Signatur-Abgleich] Test",
        text="Hinweistext mit Umlauten: äöü.",
        html="<p>Hinweis <b>HTML</b> äöü</p>",
    )


def test_build_mime_has_text_and_html():
    msg = build_mime(_draft(), "absender@example.com")
    assert msg["Subject"] == "[Signatur-Abgleich] Test"
    assert msg["From"] == "absender@example.com"
    assert msg["To"] == "empfaenger@example.com"
    assert msg.is_multipart()
    types = {p.get_content_type() for p in msg.walk()}
    assert "text/plain" in types and "text/html" in types


def test_smtp_send_end_to_end():
    with SMTPCaptureServer() as srv:
        sender = SmtpSender(
            host=srv.host, port=srv.port,
            from_addr="absender@example.com", security="none",
        )
        result = sender.send(_draft())
        srv.wait()

    assert result["status"] == "sent"
    assert result["to"] == ["empfaenger@example.com"]
    # Der Auffang-Server hat die Nachricht tatsächlich empfangen:
    assert "absender@example.com" in srv.mail_from
    assert any("empfaenger@example.com" in r for r in srv.rcpt_to)
    assert "[Signatur-Abgleich] Test" in srv.data
    assert "text/html" in srv.data  # HTML-Alternative übertragen
