"""Tests für die Review-UI (FA-40 … FA-43, FA-47)."""
from pathlib import Path

from signatur.checker import run_checker
from signatur.review_web import ReviewApp

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def _app(store, crm, config) -> ReviewApp:
    app = ReviewApp(store, "mock", config, str(SAMPLES), actor="tester@apa.at")
    app.crm = crm                      # Mock-CRM auf der Testkopie verwenden
    app.service.crm = crm
    return app


def test_arbeitsliste_zeigt_faelle_und_filter(config, store, crm):
    run_checker(SAMPLES, crm, store, config)
    html = _app(store, crm, config).worklist({}).decode("utf-8")
    assert "Arbeitsliste" in html
    assert "Sandra Bauer" in html
    assert 'name="prio"' in html and 'name="konfidenz"' in html   # FA-40


def test_arbeitsliste_filtert_nach_feldtyp(config, store, crm):
    run_checker(SAMPLES, crm, store, config)
    app = _app(store, crm, config)
    nur_adresse = app.worklist({"feld": ["address"]}).decode("utf-8")
    assert "Anna Berger" in nur_adresse and "Sandra Bauer" not in nur_adresse


def test_falldetail_zeigt_gegenueberstellung_und_kontext(config, store, crm):
    run_checker(SAMPLES, crm, store, config)
    app = _app(store, crm, config)
    case = app.service.list_cases()[0]
    html = app.case_view({"id": [case.id]}).decode("utf-8")
    assert "Abweichungen" in html                                  # FA-41
    assert "Übernehmen" in html and "Manuell" in html              # FA-42
    assert "Kontext" in html and "Empfangen" in html               # FA-43
    assert "Im CRM öffnen" in html                                 # FA-47
    assert "Audit-Log" in html                                     # FA-53


def test_kennzahlenseite_rendert(config, store, crm):
    run_checker(SAMPLES, crm, store, config)
    html = _app(store, crm, config).kpi_view().decode("utf-8")
    assert "Trefferquote" in html and "Freigabequote" in html       # Kapitel 11
