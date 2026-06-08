"""Tests für robuste Extraktion + mehrere Signaturen pro E-Mail."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signatur.crm.mock_crm import MockCrmClient
from signatur.email_loader import load_email
from signatur.models import ChangeType
from signatur.reconciler import reconcile_contact
from signatur.signature_extractor import extract_all_signatures

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
CSV = ROOT / "data" / "crm_mock.csv"


def test_messy_signature_robust_fields():
    sigs = extract_all_signatures(load_email(SAMPLES / "06_messy_signatur.eml"))
    assert len(sigs) == 1
    s = sigs[0]
    assert s.full_name == "Daniela Pereira"
    assert "Procurement" in s.job_title and s.is_decision_maker
    assert s.company == "Brightwave"               # aus Domain abgeleitet (keine Rechtsform)
    assert s.email == "d.pereira@brightwave.io"
    assert s.website == "www.brightwave.io"
    assert "linkedin.com/in/daniela-pereira" in s.linkedin
    assert "Elbchaussee 200" in s.address and "Hamburg" in s.address
    assert s.location == "Hamburg"


def test_multiple_signatures_in_one_mail():
    sigs = extract_all_signatures(
        load_email(SAMPLES / "07_weitergeleitet_zwei_signaturen.eml"))
    emails = {s.email for s in sigs}
    assert emails == {"lukas.wagner@orbit-logistics.com",
                      "sophie.martin@orbit-logistics.com"}
    by_mail = {s.email: s for s in sigs}
    assert by_mail["sophie.martin@orbit-logistics.com"].is_decision_maker  # GF
    assert by_mail["lukas.wagner@orbit-logistics.com"].company == "Orbit Logistics GmbH"


def test_html_mail_single_signature():
    # HTML-Mail darf trotz vieler <br>/Leerzeilen genau EINE Signatur ergeben
    sigs = extract_all_signatures(
        load_email(SAMPLES / "02_julia_fischer_neuer_kontakt.eml"))
    assert len(sigs) == 1
    assert sigs[0].email == "julia.fischer@helios-systems.com"
    assert "linkedin.com/in/julia-fischer" in sigs[0].linkedin


def test_address_change_is_flagged():
    client = MockCrmClient(csv_path=CSV)
    sig = extract_all_signatures(
        load_email(SAMPLES / "01_anna_berger_jobwechsel.eml"))[0]
    res = reconcile_contact(sig, client, source="t")
    changed = {d.field for d in res.discrepancies
               if d.change_type == ChangeType.FIELD_CHANGED}
    assert "address" in changed
    assert any("Adresse" in s for s in res.business_signals)


def test_email_is_primary_match_key():
    # Trifft per E-Mail, auch wenn der Name leicht abweicht
    client = MockCrmClient(csv_path=CSV)
    from signatur.models import Signature
    sig = Signature(full_name="A. Berger", email="anna.berger@muster-tech.de",
                    company="Muster Tech GmbH")
    res = reconcile_contact(sig, client, source="t")
    assert res.matched and res.match_key == "email"
