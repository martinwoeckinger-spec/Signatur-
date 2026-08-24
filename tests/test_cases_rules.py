"""Tests für Relevanzregelwerk, Matching und Fallbildung (FA-20 … FA-36)."""
import pytest

from signatur.cases import apply_rules, build_case, case_priority
from signatur.matching import match_signature
from signatur.models import (
    CaseType,
    CrmContact,
    Decision,
    DiffType,
    Signature,
    SignatureExtract,
)


def _sig(**kwargs) -> Signature:
    base = {"full_name": "Anna Berger", "email": "anna.berger@muster-tech.de",
            "confidence": {"job_title": 0.9, "company": 0.9, "phone": 0.9,
                           "mobile": 0.9, "website": 0.9, "address": 0.9,
                           "department": 0.9}}
    base.update(kwargs)
    return Signature(**base)


def _crm(**kwargs) -> CrmContact:
    base = {"crm_id": "C-1001", "full_name": "Anna Berger",
            "email": "anna.berger@muster-tech.de", "job_title": "Senior Consultant",
            "company": "Muster Tech GmbH"}
    base.update(kwargs)
    return CrmContact(**base)


def test_only_whitelisted_fields_are_compared(config, store):
    config.field_whitelist = ["job_title"]
    sig = _sig(job_title="Head of Consulting", company="CloudScale AG")
    diffs = apply_rules(sig, _crm(), config, store).diffs
    assert [d.feld for d in diffs] == ["job_title"]


def test_empty_signature_value_never_overwrites(config, store):
    # FA-33: leerer Signaturwert erzeugt keinen Vorschlag
    diffs = apply_rules(_sig(job_title=""), _crm(), config, store).diffs
    assert not diffs


def test_empty_crm_field_becomes_addition(config, store):
    # FA-34: eigener Abweichungstyp "Ergänzung"
    sig = _sig(mobile="+49 171 998 7766")
    diffs = apply_rules(sig, _crm(mobile=""), config, store).diffs
    assert [(d.feld, d.typ) for d in diffs] == [("mobile", DiffType.ERGAENZUNG)]


def test_low_confidence_field_is_dropped(config, store):
    sig = _sig(job_title="Head of Consulting",
               confidence={"job_title": 0.2})
    outcome = apply_rules(sig, _crm(), config, store)
    assert not outcome.diffs
    assert "Konfidenz" in outcome.verworfen[0]["grund"]


def test_format_only_difference_creates_no_case(config, store):
    sig = _sig(job_title="senior  consultant")
    assert not apply_rules(sig, _crm(), config, store).diffs


def test_suppressed_value_is_not_proposed_again(config, store, crm):
    from signatur.review import ReviewService

    sig = _sig(job_title="Head of Consulting")
    extract = store.add_extract(SignatureExtract(absender_email=sig.email))
    match = match_signature(sig, crm, config)
    case = build_case(extract, sig, match, config, store)
    assert case is not None and case.typ == CaseType.UPDATE
    store.add_case(case)

    ReviewService(store, crm, config).apply_decisions(
        case.id, {"job_title": {"entscheidung": "ablehnen"}}, "test@apa.at")

    # FA-35: identische Konstellation wird erneut unterdrückt
    outcome = apply_rules(sig, _crm(), config, store)
    assert not [d for d in outcome.diffs if d.feld == "job_title"]
    assert any("Suppression" in v["grund"] for v in outcome.verworfen)


def test_ambiguous_match_creates_clarification_case(config, store, crm, monkeypatch):
    # FA-22: mehrdeutige Treffer erzeugen keinen Vorschlag
    doppelt = [_crm(crm_id="C-1"), _crm(crm_id="C-2")]
    monkeypatch.setattr(crm, "find_contacts", lambda **kw: doppelt)
    sig = _sig(job_title="Head of Consulting")
    extract = store.add_extract(SignatureExtract(absender_email=sig.email))
    case = build_case(extract, sig, match_signature(sig, crm, config), config, store)
    assert case.typ == CaseType.KLAERUNG and not case.diffs
    assert len(case.kandidaten) == 2


def test_unknown_contact_creates_unknown_case(config, store, crm):
    # FA-23: kein CRM-Treffer, keine Neuanlage
    sig = _sig(full_name="Niemand Bekannt", email="niemand@unbekannt.de",
               job_title="CEO")
    extract = store.add_extract(SignatureExtract(absender_email=sig.email))
    case = build_case(extract, sig, match_signature(sig, crm, config), config, store)
    assert case.typ == CaseType.UNBEKANNT and not case.diffs


def test_name_domain_fallback_has_reduced_confidence(config, store, crm):
    # FA-21: Fallback über Name + Organisationsdomain
    sig = _sig(email="a.berger@muster-tech.de", website="www.muster-tech.de")
    match = match_signature(sig, crm, config)
    assert match.matched and match.key == "name+domain"
    assert match.confidence < 1.0


def test_repeated_proposal_raises_priority(config, store, crm):
    from signatur.cases import merge_into_open_case

    sig = _sig(job_title="Head of Consulting")
    extract = store.add_extract(SignatureExtract(absender_email=sig.email))
    match = match_signature(sig, crm, config)
    erster = build_case(extract, sig, match, config, store)
    store.add_case(erster)
    zweiter = build_case(extract, sig, match, config, store)

    vorher = erster.prio
    zusammengefuehrt = merge_into_open_case(erster, zweiter, config)
    assert zusammengefuehrt.vorkommen == 2
    assert zusammengefuehrt.prio > vorher              # FA-36
    assert len(zusammengefuehrt.diffs) == 1            # keine Dublette im Fall


def test_priority_weights_important_fields_higher(config):
    from signatur.models import Case, CaseDiff

    firma = Case(diffs=[CaseDiff(feld="company", konfidenz=0.9)])
    website = Case(diffs=[CaseDiff(feld="website", konfidenz=0.9)])
    assert case_priority(firma, config) > case_priority(website, config)


@pytest.mark.parametrize("entscheidung", [Decision.UEBERNEHMEN, Decision.ABLEHNEN])
def test_decided_diffs_do_not_count_towards_priority(config, entscheidung):
    from signatur.models import Case, CaseDiff

    case = Case(diffs=[CaseDiff(feld="company", konfidenz=0.9,
                                entscheidung=entscheidung)])
    assert case_priority(case, config) == 0
