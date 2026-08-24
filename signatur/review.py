"""Review-Service: Entscheidungen des Datenteams ausführen (FA-40 … FA-54).

Kernregel Release 1: **kein Schreiben ohne menschliche Freigabe** (FA-54).
Jede Entscheidung erzeugt einen Audit-Eintrag (FA-53); Schreibfehler lassen den
Fall offen und werden dem Bearbeiter gemeldet (FA-52).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from .config import CheckerConfig, get_config
from .crm.base import CrmClient, CrmWriteError
from .models import (
    AuditEntry,
    Case,
    CaseDiff,
    CaseStatus,
    CrmSnapshot,
    Decision,
    Suppression,
    utc_now,
)
from .cases import case_priority, contact_fields
from .normalize import normalize_value, values_equal
from .store import CheckerStore

WRITE_SOURCE = "Signature Checker"


@dataclass
class ApplyResult:
    """Ergebnis einer Freigabe-/Ablehnungsaktion für einen Fall."""

    case_id: str
    uebernommen: dict[str, str] = field(default_factory=dict)
    abgelehnt: list[str] = field(default_factory=list)
    fehler: str = ""
    modus: str = "crm"          # "crm" = geschrieben, "manuell" = zur Übernahme
    crm_link: str = ""
    status: str = ""

    @property
    def ok(self) -> bool:
        return not self.fehler

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "uebernommen": self.uebernommen,
                "abgelehnt": self.abgelehnt, "fehler": self.fehler,
                "modus": self.modus, "crm_link": self.crm_link,
                "status": self.status, "ok": self.ok}


def _age_days(case: Case) -> float:
    try:
        erstellt = datetime.fromisoformat(case.erstellt_am)
    except (TypeError, ValueError):
        return 0.0
    if erstellt.tzinfo is None:
        erstellt = erstellt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - erstellt).total_seconds() / 86400.0


class ReviewService:
    """Fachlogik hinter Arbeitsliste und Review-UI."""

    def __init__(self, store: CheckerStore, crm_client: CrmClient | None = None,
                 config: CheckerConfig | None = None) -> None:
        self.store = store
        self.crm = crm_client
        self.config = config or get_config()

    # -- Arbeitsliste (FA-40) ------------------------------------------------
    def list_cases(self, *, status: str | None = "offen", typ: str | None = None,
                   feld: str | None = None, organisation: str | None = None,
                   bearbeiter: str | None = None, min_prio: int | None = None,
                   min_konfidenz: float | None = None,
                   max_alter_tage: float | None = None,
                   sort: str = "prio") -> list[Case]:
        """Gefilterte, sortierte Fallliste."""
        cases: Iterable[Case] = self.store.cases()
        if status == "offen":
            offen = {CaseStatus.OFFEN, CaseStatus.IN_BEARBEITUNG, CaseStatus.KLAERUNG}
            cases = [c for c in cases if c.status in offen]
        elif status:
            cases = [c for c in cases if c.status.value == status]
        if typ:
            cases = [c for c in cases if c.typ.value == typ]
        if feld:
            cases = [c for c in cases if any(d.feld == feld for d in c.diffs)]
        if organisation:
            needle = organisation.lower()
            cases = [c for c in cases if needle in (c.organisation or "").lower()]
        if bearbeiter:
            cases = [c for c in cases if c.bearbeiter == bearbeiter]
        if min_prio is not None:
            cases = [c for c in cases if c.prio >= min_prio]
        if min_konfidenz is not None:
            cases = [c for c in cases
                     if c.diffs and max(d.konfidenz for d in c.diffs) >= min_konfidenz]
        if max_alter_tage is not None:
            cases = [c for c in cases if _age_days(c) <= max_alter_tage]

        cases = list(cases)
        if sort == "alter":
            cases.sort(key=lambda c: c.erstellt_am)
        elif sort == "organisation":
            cases.sort(key=lambda c: (c.organisation or "").lower())
        elif sort == "konfidenz":
            cases.sort(key=lambda c: max((d.konfidenz for d in c.diffs), default=0),
                       reverse=True)
        else:
            cases.sort(key=lambda c: (c.prio, c.vorkommen), reverse=True)
        return cases

    def organisations(self) -> list[str]:
        return sorted({c.organisation for c in self.store.cases() if c.organisation})

    def crm_link(self, case: Case) -> str:
        return self.config.crm_link(case.crm_kontakt_id)          # FA-47

    # -- Fall öffnen: CRM live nachladen (FA-24) -----------------------------
    def open_case(self, case_id: str) -> tuple[Optional[Case], dict[str, Any]]:
        """Lädt den Fall und aktualisiert die CRM-Werte zum Anzeigezeitpunkt."""
        case = self.store.get_case(case_id)
        if case is None:
            return None, {"aktualisiert": False, "grund": "Fall nicht gefunden."}
        # Öffnungszeitpunkt protokollieren – Basis für die Bearbeitungsdauer (Z-02)
        if not any(a["aktion"] == "fall_geoeffnet"
                   for a in self.store.audit(case.id)):
            self.store.add_audit(AuditEntry(case_id=case.id, aktion="fall_geoeffnet"))
        if not case.crm_kontakt_id or self.crm is None:
            return case, {"aktualisiert": False,
                          "grund": "Kein CRM-Kontakt hinterlegt."}

        kontakt = self.crm.get_contact(case.crm_kontakt_id)
        if kontakt is None:
            return case, {"aktualisiert": False,
                          "grund": "CRM-Kontakt aktuell nicht abrufbar."}

        felder = contact_fields(kontakt)
        snapshot = self.store.add_snapshot(CrmSnapshot(
            crm_kontakt_id=kontakt.crm_id, quelle=kontakt.source,
            felder={k: v for k, v in felder.items() if v}))
        case.snapshot_id = snapshot.id

        veraendert: list[str] = []
        erledigt: list[str] = []
        for diff in case.diffs:
            if diff.entscheidung != Decision.OFFEN:
                continue
            aktuell = felder.get(diff.feld, "")
            if aktuell != diff.wert_crm:
                diff.wert_crm = aktuell
                veraendert.append(diff.feld)
            if aktuell and values_equal(diff.feld, diff.wert_signatur, aktuell,
                                        self.config.default_phone_region):
                # CRM wurde zwischenzeitlich gepflegt – Vorschlag ist erledigt
                diff.entscheidung = Decision.UEBERNEHMEN
                diff.endwert = aktuell
                erledigt.append(diff.feld)
        case.prio = case_priority(case, self.config)
        self._close_if_done(case)
        self.store.put_case(case)
        return case, {"aktualisiert": True, "abgerufen_am": snapshot.abgerufen_am,
                      "geaenderte_felder": veraendert,
                      "bereits_gepflegt": erledigt}

    # -- Statusverwaltung (FA-45) --------------------------------------------
    def assign(self, case_id: str, bearbeiter: str) -> Optional[Case]:
        case = self.store.get_case(case_id)
        if case is None:
            return None
        case.bearbeiter = bearbeiter
        if case.status == CaseStatus.OFFEN:
            case.status = CaseStatus.IN_BEARBEITUNG
        self.store.put_case(case)
        self.store.add_audit(AuditEntry(case_id=case.id, aktion="zugewiesen",
                                        akteur=bearbeiter))
        return case

    def ignore_case(self, case_id: str, akteur: str, grund: str = "") -> Optional[Case]:
        """Fall ohne CRM-Änderung schliessen (FA-23: 'Ignorieren')."""
        case = self.store.get_case(case_id)
        if case is None:
            return None
        for diff in case.diffs:
            if diff.entscheidung == Decision.OFFEN:
                diff.entscheidung = Decision.ABLEHNEN
        case.status = CaseStatus.ABGELEHNT
        case.entschieden_am = utc_now()
        case.bearbeiter = case.bearbeiter or akteur
        self.store.put_case(case)
        self.store.add_audit(AuditEntry(
            case_id=case.id, aktion="fall_ignoriert", akteur=akteur,
            detail=grund or "Ohne CRM-Änderung geschlossen."))
        return case

    # -- Entscheidungen ausführen (FA-42, FA-50 … FA-54) ---------------------
    def apply_decisions(self, case_id: str,
                        entscheidungen: dict[str, dict[str, str]],
                        akteur: str) -> ApplyResult:
        """Führt feldweise Entscheidungen aus.

        `entscheidungen` bildet Feldname auf `{"entscheidung": ..., "wert": ...}`
        ab; erlaubt sind "übernehmen", "ablehnen" und "manuell" (mit Wert).
        Teilübernahmen sind ausdrücklich möglich: nicht genannte Felder bleiben
        offen und der Fall damit in Bearbeitung.
        """
        case = self.store.get_case(case_id)
        if case is None:
            return ApplyResult(case_id=case_id, fehler="Fall nicht gefunden.")
        if not akteur:
            return ApplyResult(case_id=case_id,
                               fehler="Freigabe ohne Bearbeiter ist nicht zulässig.")

        by_field = {d.feld: d for d in case.diffs}
        schreiben: dict[str, str] = {}
        abgelehnt: list[str] = []
        beruehrt: list[CaseDiff] = []

        for feld, angabe in entscheidungen.items():
            diff = by_field.get(feld)
            if diff is None or diff.entscheidung != Decision.OFFEN:
                continue
            wahl = str(angabe.get("entscheidung", "")).strip().lower()
            wert = str(angabe.get("wert", "") or "").strip()
            if wahl in ("übernehmen", "uebernehmen", "accept"):
                diff.entscheidung = Decision.UEBERNEHMEN
                diff.endwert = diff.wert_signatur
                schreiben[feld] = diff.endwert
            elif wahl in ("manuell", "manual", "korrigieren"):
                if not wert:
                    return ApplyResult(
                        case_id=case_id,
                        fehler=f"Manuelle Korrektur für '{feld}' ohne Wert.")
                diff.entscheidung = Decision.MANUELL
                diff.endwert = wert
                schreiben[feld] = wert
            elif wahl in ("ablehnen", "reject", "verwerfen"):
                diff.entscheidung = Decision.ABLEHNEN
                diff.endwert = ""
                abgelehnt.append(feld)
            else:
                continue
            beruehrt.append(diff)

        result = ApplyResult(case_id=case_id, abgelehnt=abgelehnt,
                             crm_link=self.crm_link(case))

        # Ablehnungen unterdrücken künftige identische Vorschläge (FA-35)
        for feld in abgelehnt:
            diff = by_field[feld]
            self._suppress(case, diff, akteur)
            self.store.add_audit(AuditEntry(
                case_id=case.id, aktion="feld_abgelehnt", akteur=akteur, feld=feld,
                alter_wert=diff.wert_crm, neuer_wert=diff.wert_signatur,
                quelle_extract_id=case.extract_ids[0] if case.extract_ids else ""))

        if schreiben:
            manuell = (self.crm is None or not self.crm.supports_write
                       or self.config.write_mode == "manuell")
            if manuell:
                result.modus = "manuell"
                for feld, wert in schreiben.items():
                    self.store.add_audit(AuditEntry(
                        case_id=case.id, aktion="freigabe_manuell", akteur=akteur,
                        feld=feld, alter_wert=by_field[feld].wert_crm,
                        neuer_wert=wert, ergebnis="ok",
                        detail="Zur manuellen Übernahme im CRM freigegeben "
                               f"({result.crm_link or 'kein Direktlink konfiguriert'})."))
                result.uebernommen = dict(schreiben)
            else:
                try:
                    antwort = self.crm.update_contact(
                        case.crm_kontakt_id, schreiben, actor=akteur,
                        source=WRITE_SOURCE)                       # FA-50, FA-51
                except CrmWriteError as exc:                        # FA-52
                    for feld in schreiben:
                        diff = by_field[feld]
                        diff.entscheidung = Decision.OFFEN
                        diff.endwert = ""
                        diff.fehler = str(exc)
                        self.store.add_audit(AuditEntry(
                            case_id=case.id, aktion="crm_schreibfehler", akteur=akteur,
                            feld=feld, alter_wert=diff.wert_crm,
                            neuer_wert=diff.wert_signatur, ergebnis="fehler",
                            detail=str(exc)))
                    case.status = CaseStatus.OFFEN
                    case.notizen.append(f"Schreibfehler am {utc_now()}: {exc}")
                    case.prio = case_priority(case, self.config)
                    self.store.put_case(case)
                    result.fehler = str(exc)
                    result.status = case.status.value
                    return result

                vorher = antwort.get("vorher", {}) if isinstance(antwort, dict) else {}
                for feld, wert in schreiben.items():
                    self.store.add_audit(AuditEntry(
                        case_id=case.id, aktion="feld_uebernommen", akteur=akteur,
                        feld=feld, alter_wert=vorher.get(feld, by_field[feld].wert_crm),
                        neuer_wert=wert, ergebnis="ok",
                        quelle_extract_id=case.extract_ids[0] if case.extract_ids
                        else "",
                        detail=f"Herkunft: {WRITE_SOURCE}"))
                result.uebernommen = dict(schreiben)

        for diff in beruehrt:
            diff.fehler = ""
        case.bearbeiter = case.bearbeiter or akteur
        case.prio = case_priority(case, self.config)
        self._close_if_done(case)
        self.store.put_case(case)
        result.status = case.status.value
        return result

    def bulk_apply(self, case_ids: list[str], entscheidung: str, akteur: str,
                   felder: list[str] | None = None) -> list[ApplyResult]:
        """Sammelentscheidung über mehrere Fälle bzw. Felder (FA-44)."""
        ergebnisse: list[ApplyResult] = []
        for case_id in case_ids:
            case = self.store.get_case(case_id)
            if case is None:
                continue
            ziel = {d.feld: {"entscheidung": entscheidung}
                    for d in case.diffs
                    if d.entscheidung == Decision.OFFEN
                    and (not felder or d.feld in felder)}
            if ziel:
                ergebnisse.append(self.apply_decisions(case_id, ziel, akteur))
        return ergebnisse

    # -- Sammelbenachrichtigung (FA-46) --------------------------------------
    def digest(self, seit_stunden: float | None = None) -> dict[str, Any]:
        """Kennzahlen und Fallliste für die Sammelbenachrichtigung."""
        intervall = seit_stunden if seit_stunden is not None else \
            self.config.notification_interval_minutes / 60.0
        grenze = datetime.now(timezone.utc) - timedelta(hours=intervall)
        neu: list[Case] = []
        for case in self.list_cases(status="offen"):
            try:
                erstellt = datetime.fromisoformat(case.erstellt_am)
            except (TypeError, ValueError):
                continue
            if erstellt.tzinfo is None:
                erstellt = erstellt.replace(tzinfo=timezone.utc)
            if erstellt >= grenze:
                neu.append(case)
        offen = self.list_cases(status="offen")
        zeilen = [
            f"- [{c.prio:>3}] {c.typ.value}: {c.kontakt_name or c.absender_email}"
            f" ({c.organisation or '—'}) – "
            + ", ".join(self.config.label_for(d.feld) for d in c.offene_diffs)
            for c in neu
        ]
        text = "\n".join([
            "Signature Checker – neue Fälle zur Prüfung",
            f"Zeitraum: letzte {intervall:.0f} h",
            f"Neu: {len(neu)}   Offen gesamt: {len(offen)}",
            "",
            *(zeilen or ["Keine neuen Fälle."]),
        ])
        return {"neu": len(neu), "offen_gesamt": len(offen),
                "intervall_stunden": intervall, "case_ids": [c.id for c in neu],
                "text": text}

    # -- Intern ---------------------------------------------------------------
    def _suppress(self, case: Case, diff: CaseDiff, akteur: str) -> None:
        gueltig_bis = (datetime.now(timezone.utc)
                       + timedelta(days=self.config.suppression_days))
        self.store.add_suppression(Suppression(
            crm_kontakt_id=case.crm_kontakt_id, feld=diff.feld,
            abgelehnter_wert=normalize_value(diff.feld, diff.wert_signatur,
                                             self.config.default_phone_region),
            gueltig_bis=gueltig_bis.replace(microsecond=0).isoformat(),
            akteur=akteur))

    def _close_if_done(self, case: Case) -> None:
        if case.offene_diffs:
            if case.status == CaseStatus.OFFEN and any(
                    d.entscheidung != Decision.OFFEN for d in case.diffs):
                case.status = CaseStatus.IN_BEARBEITUNG
            return
        if not case.diffs:
            return
        entschieden = {d.entscheidung for d in case.diffs}
        case.status = (CaseStatus.ABGELEHNT if entschieden == {Decision.ABLEHNEN}
                       else CaseStatus.ERLEDIGT)
        case.entschieden_am = utc_now()
