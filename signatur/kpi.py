"""Kennzahlen zur Hypothesenvalidierung (Kapitel 11 der Anforderungsdefinition).

Alle Werte werden aus Store-Daten berechnet — Extrakte, Fälle, Audit-Log —,
es gibt keine separate Zählerhaltung, die auseinanderlaufen könnte.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .config import CheckerConfig, get_config
from .models import CaseStatus, Decision, DiffType
from .store import CheckerStore

# Erfolgskriterium MVP (Kapitel 11, abzustimmen)
ZIEL_FREIGABEQUOTE = 0.60
ZIEL_BEARBEITUNGSDAUER_S = 30.0


def _ts(value: str) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _quote(zaehler: int, nenner: int) -> float:
    return round(zaehler / nenner, 3) if nenner else 0.0


def compute_kpis(store: CheckerStore, config: CheckerConfig | None = None,
                 zeitraum_tage: int | None = None) -> dict[str, Any]:
    """Berechnet die Kennzahlen; `zeitraum_tage` grenzt auf die letzten n Tage ein."""
    cfg = config or get_config()
    grenze = (datetime.now(timezone.utc) - timedelta(days=zeitraum_tage)
              if zeitraum_tage else None)

    def im_zeitraum(stamp: str) -> bool:
        if grenze is None:
            return True
        parsed = _ts(stamp)
        return parsed is not None and parsed >= grenze

    extrakte = [e for e in store.extracts if im_zeitraum(e.get("empfangen_am", ""))
                or grenze is None]
    auswertbar = [e for e in extrakte if e.get("auswertbar", True)]
    cases = [c for c in store.cases() if im_zeitraum(c.erstellt_am)]
    audit = [a for a in store.audit() if im_zeitraum(a.get("zeitpunkt", ""))]

    mit_abweichung = [c for c in cases if c.diffs]
    entschieden = [c for c in cases
                   if c.status in (CaseStatus.ERLEDIGT, CaseStatus.ABGELEHNT)]

    # Vorschläge je Feldtyp
    je_feld: dict[str, dict[str, Any]] = {}
    vorschlaege = freigegeben = abgelehnt = 0
    aktueller_als_crm = 0
    for case in cases:
        case_hat_uebernahme = False
        for diff in case.diffs:
            eintrag = je_feld.setdefault(diff.feld, {
                "label": cfg.label_for(diff.feld), "vorschlaege": 0,
                "freigegeben": 0, "abgelehnt": 0, "offen": 0})
            eintrag["vorschlaege"] += 1
            vorschlaege += 1
            if diff.entscheidung in (Decision.UEBERNEHMEN, Decision.MANUELL):
                eintrag["freigegeben"] += 1
                freigegeben += 1
                if diff.typ == DiffType.AENDERUNG:
                    case_hat_uebernahme = True
            elif diff.entscheidung == Decision.ABLEHNEN:
                eintrag["abgelehnt"] += 1
                abgelehnt += 1
            else:
                eintrag["offen"] += 1
        if case_hat_uebernahme:
            aktueller_als_crm += 1
    for eintrag in je_feld.values():
        entschieden_feld = eintrag["freigegeben"] + eintrag["abgelehnt"]
        eintrag["freigabequote"] = _quote(eintrag["freigegeben"], entschieden_feld)

    # Bearbeitungsdauer: vom Öffnen (sonst Fallanlage) bis zur Entscheidung
    dauern: list[float] = []
    geoeffnet: dict[str, datetime] = {}
    for eintrag in store.audit():
        if eintrag.get("aktion") == "fall_geoeffnet":
            stamp = _ts(eintrag.get("zeitpunkt", ""))
            if stamp and eintrag["case_id"] not in geoeffnet:
                geoeffnet[eintrag["case_id"]] = stamp
    for case in entschieden:
        ende = _ts(case.entschieden_am)
        start = geoeffnet.get(case.id) or _ts(case.erstellt_am)
        if ende and start and ende >= start:
            dauern.append((ende - start).total_seconds())
    dauer_schnitt = round(sum(dauern) / len(dauern), 1) if dauern else 0.0

    crm_updates = sum(1 for a in audit
                      if a.get("aktion") in ("feld_uebernommen", "freigabe_manuell")
                      and a.get("ergebnis") == "ok")
    schreibfehler = sum(1 for a in audit if a.get("aktion") == "crm_schreibfehler")
    aktualisierte_kontakte = len({
        c.crm_kontakt_id for c in cases if c.crm_kontakt_id and any(
            d.entscheidung in (Decision.UEBERNEHMEN, Decision.MANUELL)
            for d in c.diffs)})

    freigabequote = _quote(freigegeben, freigegeben + abgelehnt)
    return {
        "zeitraum_tage": zeitraum_tage,
        "signaturen_verarbeitet": len(auswertbar),
        "extrakte_nicht_auswertbar": len(extrakte) - len(auswertbar),
        "mails_verarbeitet": store.processed_count,
        "faelle_gesamt": len(cases),
        "faelle_mit_abweichung": len(mit_abweichung),
        "trefferquote": _quote(len(mit_abweichung), len(auswertbar)),
        "vorschlaege_gesamt": vorschlaege,
        "vorschlaege_freigegeben": freigegeben,
        "vorschlaege_abgelehnt": abgelehnt,
        "vorschlaege_offen": vorschlaege - freigegeben - abgelehnt,
        "freigabequote": freigabequote,
        "falsch_positiv_quote": _quote(abgelehnt, freigegeben + abgelehnt),
        "je_feld": je_feld,
        "faelle_signatur_aktueller": aktueller_als_crm,
        "anteil_signatur_aktueller": _quote(aktueller_als_crm, len(cases)),
        "faelle_entschieden": len(entschieden),
        "bearbeitungsdauer_schnitt_s": dauer_schnitt,
        "crm_updates": crm_updates,
        "crm_schreibfehler": schreibfehler,
        "aktualisierte_kontakte": aktualisierte_kontakte,
        "mvp_erfolgskriterium": {
            "freigabequote_ziel": ZIEL_FREIGABEQUOTE,
            "freigabequote_erreicht": freigabequote >= ZIEL_FREIGABEQUOTE,
            "bearbeitungsdauer_ziel_s": ZIEL_BEARBEITUNGSDAUER_S,
            "bearbeitungsdauer_erreicht": bool(dauern)
                                          and dauer_schnitt < ZIEL_BEARBEITUNGSDAUER_S,
        },
    }


def format_kpis(kpis: dict[str, Any]) -> str:
    """Kennzahlen als Konsolenausgabe."""
    zeile = "─" * 58
    out = [zeile, "Signature Checker – Kennzahlen (Kapitel 11)", zeile]
    zeitraum = kpis.get("zeitraum_tage")
    out.append(f"Zeitraum                     : "
               f"{'letzte ' + str(zeitraum) + ' Tage' if zeitraum else 'gesamt'}")
    out += [
        f"Mails verarbeitet            : {kpis['mails_verarbeitet']}",
        f"Signaturen ausgewertet       : {kpis['signaturen_verarbeitet']}"
        f"  (nicht auswertbar: {kpis['extrakte_nicht_auswertbar']})",
        f"Fälle gesamt                 : {kpis['faelle_gesamt']}",
        f"davon mit Abweichung         : {kpis['faelle_mit_abweichung']}"
        f"  (Trefferquote {kpis['trefferquote']:.0%})",
        f"Vorschläge                   : {kpis['vorschlaege_gesamt']} "
        f"(freigegeben {kpis['vorschlaege_freigegeben']}, "
        f"abgelehnt {kpis['vorschlaege_abgelehnt']}, "
        f"offen {kpis['vorschlaege_offen']})",
        f"Freigabequote                : {kpis['freigabequote']:.0%} "
        f"(Ziel ≥ {kpis['mvp_erfolgskriterium']['freigabequote_ziel']:.0%})",
        f"Falsch-Positiv-Quote         : {kpis['falsch_positiv_quote']:.0%} "
        "(NFA-05: ≤ 25 %)",
        f"Signatur nachweislich aktueller: {kpis['faelle_signatur_aktueller']} Fälle "
        f"({kpis['anteil_signatur_aktueller']:.0%})",
        f"Ø Bearbeitungsdauer          : {kpis['bearbeitungsdauer_schnitt_s']:.1f} s "
        f"(Ziel < {kpis['mvp_erfolgskriterium']['bearbeitungsdauer_ziel_s']:.0f} s)",
        f"CRM-Updates                  : {kpis['crm_updates']} "
        f"(Schreibfehler: {kpis['crm_schreibfehler']}, "
        f"Kontakte: {kpis['aktualisierte_kontakte']})",
        zeile,
        "Vorschläge je Feld:",
    ]
    for feld, werte in sorted(kpis["je_feld"].items(),
                              key=lambda kv: kv[1]["vorschlaege"], reverse=True):
        out.append(f"  {werte['label']:<20} {werte['vorschlaege']:>3} Vorschläge  "
                   f"freigegeben {werte['freigegeben']:>3}  "
                   f"abgelehnt {werte['abgelehnt']:>3}  "
                   f"Quote {werte['freigabequote']:.0%}")
    out.append(zeile)
    return "\n".join(out)
