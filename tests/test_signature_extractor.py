"""Tests für die Signatur-Extraktion."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signatur.models import LoadedEmail
from signatur.signature_extractor import (
    extract_from_email,
    extract_signature_block,
    parse_signature,
)

PLAIN = """Hallo,

danke fuer die Info.

Mit freundlichen Gruessen
Anna Berger
Head of Consulting
Muster Tech GmbH
Tel.: +49 89 1234-100
Mobil: +49 171 998 7766
anna.berger@muster-tech.de
www.muster-tech.de
"""


def test_block_after_greeting():
    block = extract_signature_block(PLAIN)
    assert "Anna Berger" in block
    assert "danke fuer die Info" not in block


def test_parse_core_fields():
    sig = parse_signature(extract_signature_block(PLAIN))
    assert sig.full_name == "Anna Berger"
    assert sig.first_name == "Anna" and sig.last_name == "Berger"
    assert sig.job_title == "Head of Consulting"
    assert sig.company == "Muster Tech GmbH"
    assert sig.email == "anna.berger@muster-tech.de"
    assert sig.phone.replace(" ", "") == "+49891234-100".replace(" ", "")
    assert "171" in sig.mobile
    assert "muster-tech.de" in sig.website


def test_seniority_and_decision_maker():
    sig = parse_signature(extract_signature_block(PLAIN))
    assert sig.seniority == "Leitung"
    assert sig.is_decision_maker is True


def test_dash_delimiter_block():
    body = "Text\n\n-- \nJohn Doe\nCEO\nExample Inc\njohn@example.com"
    block = extract_signature_block(body)
    assert block.startswith("John Doe")
    sig = parse_signature(block)
    assert sig.company == "Example Inc"
    assert sig.seniority == "C-Level"


def test_quoted_history_is_stripped():
    body = (
        "Beste Gruesse\nTom Klein\nNordwind AG\ntom@nordwind.at\n\n"
        "Von: jemand\nGesendet: gestern\n> alter Text mit CEO\n"
    )
    block = extract_signature_block(body)
    assert "alter Text" not in block
    assert "Tom Klein" in block


def test_fallback_from_header_name():
    mail = LoadedEmail(
        source="x", from_name="Erika Muster", from_email="erika@firma.de",
        text_body="Hallo,\n\nbis bald.\n\nViele Gruesse\nFirma XY GmbH\nTel: 0123 456789",
    )
    sig = extract_from_email(mail)
    # Name kommt aus dem From-Header, da im Block kein Personenname steht
    assert sig.full_name == "Erika Muster"
    assert sig.email == "erika@firma.de"
