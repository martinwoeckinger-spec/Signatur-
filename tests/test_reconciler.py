"""Tests für den CRM-Abgleich."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signatur.crm.mock_crm import MockCrmClient
from signatur.models import ChangeType, Signature
from signatur.reconciler import reconcile_contact

CSV = Path(__file__).resolve().parents[1] / "data" / "crm_mock.csv"


def _client():
    return MockCrmClient(csv_path=CSV)


def test_job_change_detected():
    sig = Signature(
        full_name="Anna Berger", email="anna.berger@muster-tech.de",
        job_title="Head of Consulting", company="Muster Tech GmbH",
        mobile="+49 171 998 7766", phone="+49 89 1234-100",
        seniority="Leitung", is_decision_maker=True,
    )
    res = reconcile_contact(sig, _client(), source="t")
    assert res.matched is True
    changed = {d.field for d in res.discrepancies
               if d.change_type == ChangeType.FIELD_CHANGED}
    assert "job_title" in changed
    assert "mobile" in changed
    assert any("Positionswechsel" in s or "Beförderung" in s
               for s in res.business_signals)


def test_phone_match_tolerant():
    # gleiche Nummer, andere Formatierung -> kein FIELD_CHANGED
    sig = Signature(full_name="Thomas Klein", email="thomas.klein@nordwind.at",
                    phone="+43 1 5550100")
    res = reconcile_contact(sig, _client(), source="t")
    phone_d = next(d for d in res.discrepancies if d.field == "phone")
    assert phone_d.change_type == ChangeType.MATCH


def test_new_contact_flagged():
    sig = Signature(full_name="Julia Fischer", email="julia@helios-systems.com",
                    job_title="CTO", company="Helios Systems GmbH",
                    seniority="C-Level", is_decision_maker=True)
    res = reconcile_contact(sig, _client(), source="t")
    assert res.matched is False
    assert any("nicht im CRM" in s for s in res.business_signals)
    assert res.has_actionable_changes is True


def test_match_no_action():
    sig = Signature(full_name="Marco Rossi",
                    email="marco.rossi@helvetia-solutions.ch",
                    job_title="Account Manager", company="Helvetia Solutions AG",
                    phone="+41 44 200 30 40")
    res = reconcile_contact(sig, _client(), source="t")
    assert res.matched is True
    assert res.has_actionable_changes is False
