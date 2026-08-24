"""Zuordnung eines Extrakts zu einem CRM-Kontakt (FA-20 … FA-24).

Reihenfolge: exakte E-Mail-Übereinstimmung (primärer Schlüssel), danach
optional Name + Organisationsdomain mit reduzierter Konfidenz. Mehrdeutige
Treffer führen bewusst zu keinem Vorschlag, sondern zu einem Klärungsfall.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import CheckerConfig
from .crm.base import CrmClient
from .models import CrmContact, Signature

# Konfidenz je Zuordnungsart
CONFIDENCE_EMAIL = 1.0
CONFIDENCE_NAME_DOMAIN = 0.7
CONFIDENCE_NAME_ONLY = 0.5


@dataclass
class MatchResult:
    """Ergebnis der Zuordnung inklusive Konfidenz und Kandidatenliste."""

    contact: CrmContact | None = None
    candidates: list[CrmContact] = field(default_factory=list)
    key: str = ""              # "email" | "name+domain" | "name" | ""
    confidence: float = 0.0
    ambiguous: bool = False

    @property
    def matched(self) -> bool:
        return self.contact is not None and not self.ambiguous


def organisation_domain(sig: Signature) -> str:
    """Domain der Organisation aus E-Mail-Adresse bzw. Website."""
    for value in (sig.email, sig.website):
        if not value:
            continue
        host = value.lower().split("@")[-1]
        host = re.sub(r"^[a-z]+://", "", host).split("/")[0]
        host = re.sub(r"^www\.", "", host).strip()
        if "." in host:
            return host
    return ""


def match_signature(sig: Signature, crm_client: CrmClient,
                    config: CheckerConfig) -> MatchResult:
    """Ordnet eine Signatur einem CRM-Kontakt zu."""
    if sig.email:
        hits = crm_client.find_contacts(email=sig.email)
        if len(hits) == 1:
            return MatchResult(contact=hits[0], candidates=hits, key="email",
                               confidence=CONFIDENCE_EMAIL)
        if len(hits) > 1:
            return MatchResult(contact=None, candidates=hits, key="email",
                               confidence=CONFIDENCE_EMAIL, ambiguous=True)

    if config.allow_name_domain_fallback and sig.full_name:
        domain = organisation_domain(sig)
        hits = crm_client.find_contacts(name=sig.full_name, domain=domain)
        confidence = CONFIDENCE_NAME_DOMAIN if domain else CONFIDENCE_NAME_ONLY
        key = "name+domain" if domain else "name"
        if len(hits) == 1 and confidence >= config.min_match_confidence:
            return MatchResult(contact=hits[0], candidates=hits, key=key,
                               confidence=confidence)
        if len(hits) > 1:
            return MatchResult(contact=None, candidates=hits, key=key,
                               confidence=confidence, ambiguous=True)

    return MatchResult()
