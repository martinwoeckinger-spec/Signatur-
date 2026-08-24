"""Relevanzregelwerk und Fallbildung (FA-30 … FA-36).

Trennung der Verantwortlichkeiten (NFA-10):
  * `normalize`   – Vergleichbarkeit herstellen
  * `cases`       – entscheiden, was überhaupt vorgelegt wird
  * `review`      – Entscheidungen ausführen und protokollieren

Verworfen wird hier alles, was das Datenteam nicht sehen soll: Felder ausserhalb
der Whitelist, Werte unter dem Konfidenz-Schwellwert, formatbedingte
Unterschiede, leere Signaturwerte und bereits abgelehnte Konstellationen.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import CheckerConfig
from .matching import MatchResult
from .models import (
    Case,
    CaseDiff,
    CaseStatus,
    CaseType,
    CrmContact,
    CrmSnapshot,
    Decision,
    DiffType,
    Signature,
    SignatureExtract,
    utc_now,
)
from .normalize import normalize_value, values_equal
from .store import CheckerStore

# Felder, die nie automatisch vorgeschlagen werden (Identität/Schlüssel)
NEVER_PROPOSE = {"email", "crm_id", "full_name", "first_name", "last_name"}


@dataclass
class RuleOutcome:
    """Ergebnis der Regelanwendung inkl. der Gründe für verworfene Felder."""

    diffs: list[CaseDiff]
    verworfen: list[dict[str, str]]


def contact_fields(contact: CrmContact | None) -> dict[str, str]:
    """CRM-Kontakt als Feld-Dictionary (für Snapshots und Vergleiche)."""
    if contact is None:
        return {}
    return {k: (v if isinstance(v, str) else str(v))
            for k, v in vars(contact).items()}


def signature_fields(sig: Signature) -> dict[str, str]:
    """Signatur als Feld-Dictionary ohne Rohtext und abgeleitete Flags."""
    skip = {"raw_block", "confidence", "extractor_version", "is_decision_maker"}
    return {k: v for k, v in vars(sig).items()
            if k not in skip and isinstance(v, str) and v}


def apply_rules(sig: Signature, crm: CrmContact, config: CheckerConfig,
                store: CheckerStore | None = None) -> RuleOutcome:
    """Wendet das Relevanzregelwerk auf ein Signatur/CRM-Paar an."""
    diffs: list[CaseDiff] = []
    verworfen: list[dict[str, str]] = []

    for feld in config.field_whitelist:                      # FA-32
        if feld in NEVER_PROPOSE:
            verworfen.append({"feld": feld, "grund": "Schlüssel-/Identitätsfeld"})
            continue
        sig_wert = str(getattr(sig, feld, "") or "")
        if not sig_wert:                                     # FA-33
            continue
        konfidenz = sig.confidence_of(feld)
        schwelle = config.threshold_for(feld)
        if konfidenz < schwelle:                             # FA-12
            verworfen.append({
                "feld": feld,
                "grund": f"Konfidenz {konfidenz:.2f} < Schwellwert {schwelle:.2f}",
            })
            continue

        crm_wert = str(getattr(crm, feld, "") or "")
        if crm_wert and values_equal(feld, sig_wert, crm_wert,
                                     config.default_phone_region):
            continue                                          # FA-31

        if store is not None and store.is_suppressed(
                crm.crm_id, feld, sig_wert, config.default_phone_region):
            verworfen.append({"feld": feld, "grund": "bereits abgelehnt (Suppression)"})
            continue                                          # FA-35

        diffs.append(CaseDiff(
            feld=feld,
            typ=DiffType.ERGAENZUNG if not crm_wert else DiffType.AENDERUNG,  # FA-34
            wert_crm=crm_wert,
            wert_signatur=sig_wert,
            konfidenz=round(konfidenz, 2),
        ))
    return RuleOutcome(diffs=diffs, verworfen=verworfen)


def case_priority(case: Case, config: CheckerConfig) -> int:
    """Priorität 0–100 aus Feldgewicht, Konfidenz und Wiederholungen (FA-36)."""
    if not case.diffs:
        return 20 if case.typ in (CaseType.KLAERUNG, CaseType.UNBEKANNT) else 10
    score = 0.0
    for diff in case.diffs:
        if diff.entscheidung != Decision.OFFEN:
            continue
        gewicht = config.weight_for(diff.feld)
        faktor = 1.0 if diff.typ == DiffType.AENDERUNG else 0.6
        score += gewicht * faktor * max(diff.konfidenz, 0.3)
    score *= 1 + 0.25 * max(0, case.vorkommen - 1)
    return int(max(0, min(100, round(score))))


def build_case(extract: SignatureExtract, sig: Signature, match: MatchResult,
               config: CheckerConfig, store: CheckerStore) -> Case | None:
    """Erzeugt einen Fall aus Extrakt und Zuordnung — oder `None`.

    `None` bedeutet: nach Anwendung des Regelwerks bleibt nichts Vorlagewürdiges
    übrig (keine relevante Abweichung).
    """
    kandidaten = [{"crm_id": c.crm_id, "name": c.full_name, "email": c.email,
                   "organisation": c.company} for c in match.candidates]

    if match.ambiguous:                                       # FA-22
        klaerung = Case(
            typ=CaseType.KLAERUNG, status=CaseStatus.KLAERUNG,
            crm_kontakt_id="", kontakt_name=sig.full_name, organisation=sig.company,
            absender_email=sig.email, extract_ids=[extract.id],
            match_konfidenz=match.confidence, kandidaten=kandidaten,
            notizen=[f"{len(match.candidates)} mögliche CRM-Kontakte – "
                     f"manuelle Zuordnung erforderlich."],
        )
        klaerung.prio = case_priority(klaerung, config)
        return klaerung

    if match.contact is None:                                 # FA-23
        unbekannt = Case(
            typ=CaseType.UNBEKANNT, status=CaseStatus.OFFEN,
            crm_kontakt_id="", kontakt_name=sig.full_name, organisation=sig.company,
            absender_email=sig.email, extract_ids=[extract.id],
            match_konfidenz=0.0,
            notizen=["Kein CRM-Treffer – Neuanlage ist in Release 1 nicht "
                     "vorgesehen (Option: ignorieren)."],
        )
        unbekannt.prio = case_priority(unbekannt, config)
        return unbekannt

    crm = match.contact
    outcome = apply_rules(sig, crm, config, store)
    if not outcome.diffs:
        return None

    snapshot = store.add_snapshot(CrmSnapshot(
        crm_kontakt_id=crm.crm_id, quelle=crm.source,
        felder={k: v for k, v in contact_fields(crm).items() if v},
    ))

    typ = CaseType.UPDATE if any(d.typ == DiffType.AENDERUNG for d in outcome.diffs) \
        else CaseType.ERGAENZUNG
    case = Case(
        typ=typ, status=CaseStatus.OFFEN, crm_kontakt_id=crm.crm_id,
        kontakt_name=crm.full_name or sig.full_name,
        organisation=crm.company or sig.company,
        absender_email=sig.email or crm.email,
        extract_ids=[extract.id], snapshot_id=snapshot.id,
        match_konfidenz=match.confidence, kandidaten=kandidaten,
        diffs=outcome.diffs,
    )
    for diff in case.diffs:
        diff.case_id = case.id
    if outcome.verworfen:
        case.notizen.extend(
            f"Feld '{config.label_for(v['feld'])}' verworfen: {v['grund']}"
            for v in outcome.verworfen)
    case.prio = case_priority(case, config)
    return case


def merge_into_open_case(existing: Case, neu: Case, config: CheckerConfig) -> Case:
    """Aggregiert einen neuen Fall in einen bereits offenen Fall (FA-36)."""
    bekannt = {(d.feld, normalize_value(d.feld, d.wert_signatur,
                                        config.default_phone_region))
               for d in existing.diffs}
    neue_diffs = 0
    for diff in neu.diffs:
        key = (diff.feld, normalize_value(diff.feld, diff.wert_signatur,
                                          config.default_phone_region))
        if key in bekannt:
            continue
        diff.case_id = existing.id
        existing.diffs.append(diff)
        bekannt.add(key)
        neue_diffs += 1

    existing.vorkommen += 1
    existing.extract_ids.extend(
        eid for eid in neu.extract_ids if eid not in existing.extract_ids)
    if neu.snapshot_id:
        existing.snapshot_id = neu.snapshot_id
    existing.aktualisiert_am = utc_now()
    existing.notizen.append(
        f"Erneut bestätigt am {utc_now()} "
        f"({neue_diffs} neue Abweichung(en), Vorkommen: {existing.vorkommen})."
    )
    existing.prio = case_priority(existing, config)
    return existing
