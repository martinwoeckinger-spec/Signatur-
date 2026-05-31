"""Datenmodelle für den Signatur-/CRM-Workflow."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


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


@dataclass
class Signature:
    """Aus einer Signatur extrahierter geschäftsrelevanter Kontext."""

    # Roh-Block, aus dem extrahiert wurde
    raw_block: str = ""

    # Kernfelder
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
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

    # Abgeleiteter Business-Kontext
    seniority: str = ""          # z. B. "C-Level", "Leitung", "Fachkraft"
    is_decision_maker: bool = False
    location: str = ""           # grob aus Adresse abgeleitet

    def is_empty(self) -> bool:
        return not any(
            [self.full_name, self.job_title, self.company, self.phone,
             self.mobile, self.email, self.website]
        )


@dataclass
class CrmContact:
    """Ein Kontaktdatensatz aus dem CRM (quellenunabhängig normalisiert)."""

    crm_id: str = ""
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    job_title: str = ""
    department: str = ""
    company: str = ""
    email: str = ""
    phone: str = ""
    mobile: str = ""
    website: str = ""
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
