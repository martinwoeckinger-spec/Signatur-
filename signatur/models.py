"""Datenmodelle für den Signatur-/CRM-Workflow.

Enthält die operativen Modelle des Prototyps (`LoadedEmail`, `Signature`,
`CrmContact`, `ContactReconciliation`) sowie die fachlichen Entitäten aus
Kapitel 9 der Anforderungsdefinition (`SignatureExtract`, `CrmSnapshot`,
`Case`, `CaseDiff`, `AuditEntry`, `Suppression`).
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def new_id(prefix: str) -> str:
    """Kurze, stabile ID mit sprechendem Präfix (z. B. 'case-1a2b3c4d')."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utc_now() -> str:
    """Zeitstempel in ISO-8601 (UTC, sekundengenau) für Protokolle."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class LoadedEmail:
    """Eine geladene E-Mail (aus .eml/.msg) in normalisierter Form."""

    source: str  # Dateipfad/Herkunft
    from_name: str = ""
    from_email: str = ""
    subject: str = ""
    date: str = ""
    text_body: str = ""
    html_body: str = ""
    message_id: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    inline_images: int = 0

    def header(self, name: str) -> str:
        """Header-Zugriff ohne Rücksicht auf Groß-/Kleinschreibung."""
        return self.headers.get(name.lower(), "")


@dataclass
class Signature:
    """Aus einer Signatur extrahierter geschäftsrelevanter Kontext."""

    # Roh-Block, aus dem extrahiert wurde
    raw_block: str = ""

    # Kernfelder
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    academic_title: str = ""     # akad. Grad, z. B. "Dr.", "Prof. Dr."
    job_title: str = ""
    department: str = ""
    company: str = ""
    email: str = ""
    phone: str = ""
    mobile: str = ""
    fax: str = ""
    website: str = ""
    linkedin: str = ""
    address: str = ""

    # Adresse strukturiert (FA-11)
    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = ""

    # Abgeleiteter Business-Kontext
    seniority: str = ""          # z. B. "C-Level", "Leitung", "Fachkraft"
    is_decision_maker: bool = False
    location: str = ""           # grob aus Adresse abgeleitet

    # Qualität/Herkunft der Extraktion (FA-12, FA-15)
    confidence: dict[str, float] = field(default_factory=dict)
    extractor_version: str = ""

    def is_empty(self) -> bool:
        return not any(
            [self.full_name, self.job_title, self.company, self.phone,
             self.mobile, self.email, self.website]
        )

    def confidence_of(self, field_name: str) -> float:
        return float(self.confidence.get(field_name, 0.0))


@dataclass
class CrmContact:
    """Ein Kontaktdatensatz aus dem CRM (quellenunabhängig normalisiert)."""

    crm_id: str = ""
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    academic_title: str = ""
    job_title: str = ""
    department: str = ""
    company: str = ""
    email: str = ""
    phone: str = ""
    mobile: str = ""
    website: str = ""
    address: str = ""
    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = ""
    linkedin: str = ""
    source: str = ""  # z. B. "mock", "sap-sales-cloud"


class ChangeType(str, Enum):
    NEW_CONTACT = "NEW_CONTACT"            # Kontakt nicht im CRM gefunden
    FIELD_CHANGED = "FIELD_CHANGED"        # Wert weicht ab
    FIELD_NEW_IN_CRM = "FIELD_NEW_IN_CRM"  # Signatur liefert Wert, CRM leer
    MATCH = "MATCH"                        # Werte stimmen überein


@dataclass
class Discrepancy:
    field: str
    change_type: ChangeType
    signature_value: str = ""
    crm_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["change_type"] = self.change_type.value
        return d


@dataclass
class ContactReconciliation:
    """Abgleich-Ergebnis für genau einen Kontakt/eine Mail."""

    source: str
    signature: Signature
    crm_contact: Optional[CrmContact] = None
    matched: bool = False
    match_key: str = ""                 # wonach gematcht wurde (email/name)
    match_confidence: float = 0.0       # Konfidenz der Zuordnung (FA-21)
    ambiguous: bool = False             # mehrdeutiger Treffer (FA-22)
    candidates: list[CrmContact] = field(default_factory=list)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    business_signals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def has_actionable_changes(self) -> bool:
        return (not self.matched) or any(
            d.change_type in (ChangeType.FIELD_CHANGED, ChangeType.FIELD_NEW_IN_CRM)
            for d in self.discrepancies
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "matched": self.matched,
            "match_key": self.match_key,
            "match_confidence": self.match_confidence,
            "ambiguous": self.ambiguous,
            "signature": asdict(self.signature),
            "crm_contact": asdict(self.crm_contact) if self.crm_contact else None,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "business_signals": self.business_signals,
            "notes": self.notes,
            "has_actionable_changes": self.has_actionable_changes,
        }


@dataclass
class ReconciliationReport:
    """Gesamtergebnis über alle verarbeiteten Mails."""

    results: list[ContactReconciliation] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "processed": len(self.results),
                "new_contacts": sum(1 for r in self.results if not r.matched),
                "with_changes": sum(1 for r in self.results if r.has_actionable_changes),
                "skipped": len(self.skipped),
            },
            "results": [r.to_dict() for r in self.results],
            "skipped": self.skipped,
        }


# --- Fachliche Entitäten (Kapitel 9 der Anforderungsdefinition) --------------

@dataclass
class SignatureExtract:
    """Strukturierter Datensatz aus einem Signaturblock.

    Persistiert werden ausschließlich Metadaten und der Signaturblock —
    nie der vollständige Nachrichtentext (FA-03).
    """

    id: str = field(default_factory=lambda: new_id("ext"))
    message_id: str = ""
    empfangen_am: str = ""
    absender_email: str = ""
    quelle: str = ""                 # Dateiname/Postfach-Referenz
    betreff: str = ""
    rohtext_signatur: str = ""
    felder: dict[str, str] = field(default_factory=dict)
    konfidenz: dict[str, float] = field(default_factory=dict)
    verfahrensversion: str = ""
    auswertbar: bool = True          # False z. B. bei Bildsignatur (FA-16)
    hinweis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CrmSnapshot:
    """Momentaufnahme eines CRM-Kontakts zum Abrufzeitpunkt."""

    id: str = field(default_factory=lambda: new_id("snap"))
    crm_kontakt_id: str = ""
    abgerufen_am: str = field(default_factory=utc_now)
    quelle: str = ""
    felder: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CaseType(str, Enum):
    UPDATE = "Update"
    ERGAENZUNG = "Ergänzung"
    KLAERUNG = "Klärung"
    UNBEKANNT = "Unbekannt"


class CaseStatus(str, Enum):
    OFFEN = "offen"
    IN_BEARBEITUNG = "in Bearbeitung"
    ERLEDIGT = "erledigt"
    ABGELEHNT = "abgelehnt"
    KLAERUNG = "Klärung"


class Decision(str, Enum):
    OFFEN = "offen"
    UEBERNEHMEN = "übernehmen"
    ABLEHNEN = "ablehnen"
    MANUELL = "manuell"


class DiffType(str, Enum):
    AENDERUNG = "Änderung"     # CRM-Wert vorhanden und abweichend
    ERGAENZUNG = "Ergänzung"   # CRM-Feld leer, Signatur liefert Wert


@dataclass
class CaseDiff:
    """Feldbezogene Abweichung innerhalb eines Falls."""

    id: str = field(default_factory=lambda: new_id("diff"))
    case_id: str = ""
    feld: str = ""
    typ: DiffType = DiffType.AENDERUNG
    wert_crm: str = ""
    wert_signatur: str = ""
    konfidenz: float = 0.0
    entscheidung: Decision = Decision.OFFEN
    endwert: str = ""
    fehler: str = ""            # letzter Schreibfehler (FA-52)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["typ"] = self.typ.value
        d["entscheidung"] = self.entscheidung.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CaseDiff":
        return cls(
            id=d.get("id", new_id("diff")), case_id=d.get("case_id", ""),
            feld=d.get("feld", ""), typ=DiffType(d.get("typ", DiffType.AENDERUNG.value)),
            wert_crm=d.get("wert_crm", ""), wert_signatur=d.get("wert_signatur", ""),
            konfidenz=float(d.get("konfidenz", 0.0)),
            entscheidung=Decision(d.get("entscheidung", Decision.OFFEN.value)),
            endwert=d.get("endwert", ""), fehler=d.get("fehler", ""),
        )


@dataclass
class Case:
    """Bearbeitungseinheit für das Datenteam: Match + n Abweichungen."""

    id: str = field(default_factory=lambda: new_id("case"))
    typ: CaseType = CaseType.UPDATE
    crm_kontakt_id: str = ""
    kontakt_name: str = ""
    organisation: str = ""
    absender_email: str = ""
    status: CaseStatus = CaseStatus.OFFEN
    prio: int = 0
    erstellt_am: str = field(default_factory=utc_now)
    aktualisiert_am: str = field(default_factory=utc_now)
    bearbeiter: str = ""
    entschieden_am: str = ""
    extract_ids: list[str] = field(default_factory=list)
    snapshot_id: str = ""
    vorkommen: int = 1                 # Aggregation gleicher Vorschläge (FA-36)
    match_konfidenz: float = 0.0
    kandidaten: list[dict[str, str]] = field(default_factory=list)  # FA-22
    diffs: list[CaseDiff] = field(default_factory=list)
    notizen: list[str] = field(default_factory=list)

    @property
    def offene_diffs(self) -> list[CaseDiff]:
        return [d for d in self.diffs if d.entscheidung == Decision.OFFEN]

    @property
    def dedupe_key(self) -> str:
        """Schlüssel für die Deduplizierung offener Fälle (FA-36)."""
        ref = self.crm_kontakt_id or f"mail:{self.absender_email}"
        return f"{self.typ.value}|{ref}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["typ"] = self.typ.value
        d["status"] = self.status.value
        d["diffs"] = [x.to_dict() for x in self.diffs]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        case = cls(
            id=d.get("id", new_id("case")),
            typ=CaseType(d.get("typ", CaseType.UPDATE.value)),
            crm_kontakt_id=d.get("crm_kontakt_id", ""),
            kontakt_name=d.get("kontakt_name", ""),
            organisation=d.get("organisation", ""),
            absender_email=d.get("absender_email", ""),
            status=CaseStatus(d.get("status", CaseStatus.OFFEN.value)),
            prio=int(d.get("prio", 0)),
            erstellt_am=d.get("erstellt_am", utc_now()),
            aktualisiert_am=d.get("aktualisiert_am", utc_now()),
            bearbeiter=d.get("bearbeiter", ""),
            entschieden_am=d.get("entschieden_am", ""),
            extract_ids=list(d.get("extract_ids", [])),
            snapshot_id=d.get("snapshot_id", ""),
            vorkommen=int(d.get("vorkommen", 1)),
            match_konfidenz=float(d.get("match_konfidenz", 0.0)),
            kandidaten=list(d.get("kandidaten", [])),
            notizen=list(d.get("notizen", [])),
        )
        case.diffs = [CaseDiff.from_dict(x) for x in d.get("diffs", [])]
        return case


@dataclass
class AuditEntry:
    """Revisionssicherer Protokolleintrag (FA-53, NFA-07)."""

    id: str = field(default_factory=lambda: new_id("audit"))
    case_id: str = ""
    aktion: str = ""            # z. B. "fall_erstellt", "feld_uebernommen"
    akteur: str = "system"
    zeitpunkt: str = field(default_factory=utc_now)
    feld: str = ""
    alter_wert: str = ""
    neuer_wert: str = ""
    ergebnis: str = "ok"        # ok | fehler
    quelle_message_id: str = ""
    quelle_extract_id: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Suppression:
    """Unterdrückung erneut vorgeschlagener, bereits abgelehnter Werte (FA-35)."""

    crm_kontakt_id: str = ""
    feld: str = ""
    abgelehnter_wert: str = ""     # normalisierter Wert
    gueltig_bis: str = ""
    angelegt_am: str = field(default_factory=utc_now)
    akteur: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
