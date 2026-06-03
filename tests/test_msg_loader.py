"""Test des .msg-Imports (Echtdaten-Pfad) ueber den olefile-Parser.

Erzeugt zur Laufzeit eine minimale, echte .msg (kein Binaer-Fixture im Repo)
und prueft Laden + Signatur-Extraktion.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

olefile = pytest.importorskip("olefile")  # noqa: F841

from cfb_writer import build_msg

from signatur.email_loader import load_email
from signatur.signature_extractor import extract_from_email

_BODY = (
    "Hallo,\r\n\r\nanbei die Unterlagen.\r\n\r\n"
    "Mit freundlichen Gruessen\r\n"
    "Erika Musterfrau\r\n"
    "Leiterin Einkauf\r\n"
    "Muster AG\r\n"
    "Tel: +49 89 123456\r\n"
    "erika@muster-ag.de\r\n"
)

_PROPS = {
    "0037": "Angebot Q3",          # PR_SUBJECT
    "1000": _BODY,                 # PR_BODY
    "0C1A": "Erika Musterfrau",    # PR_SENDER_NAME
    "0C1F": "erika@muster-ag.de",  # PR_SENDER_EMAIL_ADDRESS
}


def _write_msg(tmp_path) -> Path:
    p = tmp_path / "echt.msg"
    p.write_bytes(build_msg(_PROPS))
    return p


def test_generated_file_is_valid_ole(tmp_path):
    p = _write_msg(tmp_path)
    assert olefile.isOleFile(str(p))


def test_msg_load_fields(tmp_path):
    mail = load_email(_write_msg(tmp_path))
    assert mail.subject == "Angebot Q3"
    assert mail.from_email == "erika@muster-ag.de"
    assert mail.from_name == "Erika Musterfrau"
    assert "Muster AG" in mail.text_body


def test_msg_signature_extraction(tmp_path):
    sig = extract_from_email(load_email(_write_msg(tmp_path)))
    assert sig.full_name == "Erika Musterfrau"
    assert sig.company == "Muster AG"
    assert "Leiterin" in sig.job_title
    assert sig.email == "erika@muster-ag.de"
    assert sig.seniority == "Leitung"
    assert sig.is_decision_maker is True
