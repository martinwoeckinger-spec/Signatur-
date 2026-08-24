"""Tests für Kennzahlen (Kapitel 11), Aufbewahrung (DS-04) und Auskunft (DS-06)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from signatur.checker import run_checker
from signatur.kpi import compute_kpis
from signatur.models import SignatureExtract

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def test_kpis_nach_freigabe(config, store, crm, service):
    run_checker(SAMPLES, crm, store, config)
    case = next(c for c in service.list_cases() if c.diffs)
    service.open_case(case.id)
    service.apply_decisions(
        case.id,
        {d.feld: {"entscheidung": "übernehmen" if i == 0 else "ablehnen"}
         for i, d in enumerate(case.diffs)},
        akteur="datenteam@apa.at")

    kpis = compute_kpis(store, config)
    assert kpis["signaturen_verarbeitet"] == 7
    assert kpis["faelle_gesamt"] >= 1
    assert 0.0 < kpis["trefferquote"] <= 1.0
    assert kpis["vorschlaege_freigegeben"] == 1
    assert kpis["vorschlaege_abgelehnt"] == len(case.diffs) - 1
    assert kpis["crm_updates"] == 1
    assert kpis["aktualisierte_kontakte"] == 1
    assert kpis["faelle_signatur_aktueller"] == 1
    assert kpis["faelle_entschieden"] == 1
    assert kpis["je_feld"][case.diffs[0].feld]["freigegeben"] == 1
    assert "freigabequote_ziel" in kpis["mvp_erfolgskriterium"]


def test_kpis_ohne_daten_sind_null(store, config):
    kpis = compute_kpis(store, config)
    assert kpis["faelle_gesamt"] == 0 and kpis["freigabequote"] == 0.0


def test_purge_loescht_alte_rohsignaturen(store, config):
    alt = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    store.add_extract(SignatureExtract(empfangen_am=alt, absender_email="a@x.de",
                                       rohtext_signatur="Anna Berger\nCEO"))
    result = store.purge_expired(90)                                   # DS-04
    assert result["extrakte_geloescht"] == 1
    assert not store.extracts


def test_purge_behaelt_referenzierte_extrakte_ohne_rohtext(store, config, crm):
    run_checker(SAMPLES / "01_anna_berger_jobwechsel.eml", crm, store, config)
    extrakt_id = store.extracts[0]["id"]
    store.data["extracts"][0]["empfangen_am"] = (
        datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    store.save()
    result = store.purge_expired(90)
    assert result["extrakte_bereinigt"] == 1
    assert store.get_extract(extrakt_id)["rohtext_signatur"] == ""


def test_auskunft_und_loeschung(store, config, crm):
    run_checker(SAMPLES, crm, store, config)
    auskunft = store.find_by_person("anna.berger@muster-tech.de")      # DS-06
    assert auskunft["extracts"] and auskunft["cases"]
    geloescht = store.delete_person("anna.berger@muster-tech.de")
    assert geloescht["extrakte"] >= 1
    assert not store.find_by_person("anna.berger@muster-tech.de")["cases"]
    assert store.audit()                                               # Audit bleibt
