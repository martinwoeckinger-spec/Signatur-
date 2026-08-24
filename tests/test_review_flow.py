"""End-to-End: E-Mail → Fall → Freigabe → CRM-Änderung → Audit (Abnahme 13.3)."""
from pathlib import Path

from signatur.checker import run_checker
from signatur.crm.base import CrmWriteError
from signatur.models import CaseStatus, Decision

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def _case_for(service, name: str):
    return next(c for c in service.list_cases(status=None)
                if c.kontakt_name.startswith(name))


def test_end_to_end_freigabe_schreibt_ins_crm(config, store, crm, service):
    report = run_checker(SAMPLES, crm, store, config)
    assert report.verarbeitet == 7 and report.faelle_neu

    case = _case_for(service, "Sandra Bauer")
    result = service.apply_decisions(case.id, {
        "job_title": {"entscheidung": "übernehmen"},
        "company": {"entscheidung": "ablehnen"},
        "phone": {"entscheidung": "manuell", "wert": "+49 30 9911 999"},
        "website": {"entscheidung": "übernehmen"},
    }, akteur="datenteam@apa.at")

    assert result.ok and result.modus == "crm"
    kontakt = crm.get_contact(case.crm_kontakt_id)
    assert kontakt.job_title == "Head of Engineering"        # FA-50
    assert kontakt.phone == "+49 30 9911 999"                # FA-42 manuell
    assert kontakt.company == "TechnoVision GmbH"            # abgelehnt

    zeile = next(r for r in crm.rows if r["crm_id"] == case.crm_kontakt_id)
    assert zeile["last_change_source"] == "Signature Checker"   # FA-51
    assert zeile["last_change_by"] == "datenteam@apa.at"

    aktionen = [a["aktion"] for a in store.audit(case.id)]     # FA-53
    assert "fall_erstellt" in aktionen and "feld_uebernommen" in aktionen
    uebernommen = [a for a in store.audit(case.id)
                   if a["aktion"] == "feld_uebernommen" and a["feld"] == "job_title"]
    assert uebernommen[0]["alter_wert"] == "Senior Developer"
    assert uebernommen[0]["neuer_wert"] == "Head of Engineering"

    geschlossen = store.get_case(case.id)
    assert geschlossen.status == CaseStatus.ERLEDIGT
    assert geschlossen.entschieden_am


def test_teiluebernahme_laesst_fall_in_bearbeitung(config, store, crm, service):
    run_checker(SAMPLES, crm, store, config)
    case = _case_for(service, "Anna Berger")
    service.apply_decisions(case.id, {"job_title": {"entscheidung": "übernehmen"}},
                            akteur="datenteam@apa.at")
    aktuell = store.get_case(case.id)
    assert aktuell.status == CaseStatus.IN_BEARBEITUNG
    assert {d.feld for d in aktuell.offene_diffs} == {"mobile", "address"}


def test_schreibfehler_laesst_fall_offen(config, store, crm, service, monkeypatch):
    run_checker(SAMPLES, crm, store, config)
    case = _case_for(service, "Anna Berger")

    def kaputt(*args, **kwargs):
        raise CrmWriteError("CRM nicht erreichbar")

    monkeypatch.setattr(crm, "update_contact", kaputt)
    result = service.apply_decisions(
        case.id, {"job_title": {"entscheidung": "übernehmen"}}, "datenteam@apa.at")

    assert not result.ok and "nicht erreichbar" in result.fehler      # FA-52
    offen = store.get_case(case.id)
    assert offen.status == CaseStatus.OFFEN
    diff = next(d for d in offen.diffs if d.feld == "job_title")
    assert diff.entscheidung == Decision.OFFEN and "nicht erreichbar" in diff.fehler
    assert any(a["ergebnis"] == "fehler" for a in store.audit(case.id))


def test_freigabe_ohne_bearbeiter_wird_abgelehnt(config, store, crm, service):
    run_checker(SAMPLES, crm, store, config)
    case = _case_for(service, "Anna Berger")
    result = service.apply_decisions(
        case.id, {"job_title": {"entscheidung": "übernehmen"}}, akteur="")
    assert not result.ok                                              # FA-54


def test_live_abruf_erkennt_zwischenzeitliche_pflege(config, store, crm, service):
    run_checker(SAMPLES, crm, store, config)
    case = _case_for(service, "Anna Berger")
    # CRM wird ausserhalb des Tools gepflegt
    crm.update_contact(case.crm_kontakt_id, {"job_title": "Head of Consulting"},
                       actor="crm-admin")

    frisch, info = service.open_case(case.id)                        # FA-24
    assert info["aktualisiert"] and "job_title" in info["bereits_gepflegt"]
    diff = next(d for d in frisch.diffs if d.feld == "job_title")
    assert diff.entscheidung == Decision.UEBERNEHMEN


def test_manueller_modus_schreibt_nicht_ins_crm(config, store, crm, service):
    config.write_mode = "manuell"
    run_checker(SAMPLES, crm, store, config)
    case = _case_for(service, "Anna Berger")
    vorher = crm.get_contact(case.crm_kontakt_id).job_title
    result = service.apply_decisions(
        case.id, {"job_title": {"entscheidung": "übernehmen"}}, "datenteam@apa.at")
    assert result.modus == "manuell" and result.ok
    assert result.crm_link.endswith(case.crm_kontakt_id)             # FA-47
    assert crm.get_contact(case.crm_kontakt_id).job_title == vorher
    assert any(a["aktion"] == "freigabe_manuell" for a in store.audit(case.id))


def test_bulk_aktion_ueber_mehrere_faelle(config, store, crm, service):
    run_checker(SAMPLES, crm, store, config)
    ids = [c.id for c in service.list_cases() if c.diffs][:2]
    ergebnisse = service.bulk_apply(ids, "übernehmen", "datenteam@apa.at")  # FA-44
    assert len(ergebnisse) == 2 and all(r.ok for r in ergebnisse)
    assert all(store.get_case(i).status == CaseStatus.ERLEDIGT for i in ids)


def test_unbekannter_kontakt_kann_ignoriert_werden(config, store, crm, service):
    run_checker(SAMPLES, crm, store, config)
    case = _case_for(service, "Julia Fischer")
    service.ignore_case(case.id, "datenteam@apa.at", grund="kein Kunde")  # FA-23
    assert store.get_case(case.id).status == CaseStatus.ABGELEHNT


def test_idempotenz_und_aggregation(config, store, crm, service):
    run_checker(SAMPLES, crm, store, config)
    zweiter = run_checker(SAMPLES, crm, store, config)
    assert zweiter.dubletten == 7 and not zweiter.faelle_neu          # FA-05

    store.data["processed_messages"].clear()
    store.save()
    dritter = run_checker(SAMPLES, crm, store, config)
    assert dritter.faelle_aggregiert and not dritter.faelle_neu       # FA-36
    assert all(c.vorkommen >= 2 for c in service.list_cases())


def test_nur_signaturblock_wird_persistiert(config, store, crm):
    run_checker(SAMPLES / "01_anna_berger_jobwechsel.eml", crm, store, config)
    extrakt = store.extracts[0]
    assert extrakt["rohtext_signatur"]                                # FA-03
    assert "danke" not in extrakt["rohtext_signatur"].lower()
    assert "text_body" not in extrakt and "rohtext_mail" not in extrakt
