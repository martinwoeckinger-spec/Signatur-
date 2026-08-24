"""Tests für die Konfidenzbewertung je Feld (FA-12)."""
from signatur.confidence import score_signature
from signatur.models import LoadedEmail
from signatur.signature_extractor import parse_signature

BLOCK = """Anna Berger
Head of Consulting
Muster Tech GmbH
Tel.: +49 89 1234-100
Mobil: +49 171 998 7766
anna.berger@muster-tech.de
www.muster-tech.de
Innovationsstrasse 5
80331 Muenchen
"""


def test_confidence_between_zero_and_one():
    sig = parse_signature(BLOCK, block_source="delimiter")
    assert sig.confidence
    assert all(0.0 <= v <= 1.0 for v in sig.confidence.values())


def test_sender_address_gets_highest_confidence():
    mail = LoadedEmail(source="x", from_email="anna.berger@muster-tech.de")
    scores = score_signature(parse_signature(BLOCK), mail, block_source="delimiter")
    assert scores["email"] == 1.0


def test_legal_form_raises_company_confidence():
    mit_rechtsform = parse_signature(BLOCK, block_source="delimiter")
    ohne = parse_signature(BLOCK.replace("Muster Tech GmbH", "Muster Tech"),
                           block_source="delimiter")
    assert mit_rechtsform.confidence_of("company") > ohne.confidence_of("company")


def test_tail_heuristic_lowers_confidence():
    sicher = parse_signature(BLOCK, block_source="delimiter")
    unsicher = parse_signature(BLOCK, block_source="tail")
    assert unsicher.confidence_of("job_title") < sicher.confidence_of("job_title")


def test_labelled_phone_beats_unlabelled():
    ohne_label = parse_signature(BLOCK.replace("Tel.: ", ""), block_source="delimiter")
    mit_label = parse_signature(BLOCK, block_source="delimiter")
    assert mit_label.confidence_of("phone") > ohne_label.confidence_of("phone")


def test_extractor_version_is_recorded():
    # FA-15: die Verfahrensversion wird je Extrakt protokolliert
    assert parse_signature(BLOCK).extractor_version.startswith("rules-")
