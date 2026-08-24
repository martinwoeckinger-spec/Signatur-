"""Konfidenzbewertung je extrahiertem Feld (FA-12).

Die Bewertung ist regelbasiert und erklärbar: Sie bewertet, wie eindeutig das
Signal war, aus dem ein Feld gewonnen wurde (Label vorhanden, Rechtsform,
Domain-Übereinstimmung, Treffer der Absenderadresse …). Werte liegen in [0, 1].
Felder unterhalb des konfigurierten Schwellwerts werden später nicht als
Vorschlag verwendet — die Bewertung selbst kennt die Schwellwerte nicht.
"""
from __future__ import annotations

import re

from .models import LoadedEmail, Signature
from .normalize import normalize_phone

# Wie sicher war die Abgrenzung des Signaturblocks selbst?
BLOCK_FACTORS = {
    "delimiter": 1.0,    # "-- " Trenner nach RFC-Konvention
    "greeting": 0.97,    # nach Grußformel
    "tail": 0.85,        # letzte Zeilen der Mail (Heuristik)
    "header": 0.8,       # nur aus Mail-Headern abgeleitet
    "unknown": 0.95,
}

_LABEL_RES = {
    "phone": re.compile(r"\b(tel|telefon|phone|fon|festnetz|office|durchwahl|t)\b\s*[:.]",
                        re.I),
    "mobile": re.compile(r"\b(mobil|mobile|cell|handy|m)\b\s*[:.]", re.I),
    "fax": re.compile(r"\b(fax|telefax|f)\b\s*[:.]", re.I),
    "website": re.compile(r"\b(web|website|homepage|url|internet)\b\s*[:.]?", re.I),
    "department": re.compile(r"\b(abteilung|department|team|bereich|unit)\b", re.I),
    "job_title": re.compile(r"\b(position|funktion|role|rolle|title)\b\s*[:.]", re.I),
}

_PLZ_CITY = re.compile(r"\b\d{4,5}\s+[A-ZÄÖÜ]")


def _domain(value: str) -> str:
    if not value:
        return ""
    host = value.lower().split("@")[-1]
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0]
    return re.sub(r"^www\.", "", host)


def _line_with(block: str, needle: str) -> str:
    if not needle:
        return ""
    for line in block.splitlines():
        if needle.lower() in line.lower():
            return line
    return ""


def score_signature(sig: Signature, mail: LoadedEmail | None = None,
                    block_source: str = "unknown") -> dict[str, float]:
    """Berechnet Konfidenzwerte für alle gefüllten Felder einer Signatur."""
    from .signature_extractor import (  # lazy: vermeidet Zirkelimport
        _detect_seniority,
        _has_company_hint,
    )

    block = sig.raw_block or ""
    factor = BLOCK_FACTORS.get(block_source, BLOCK_FACTORS["unknown"])
    scores: dict[str, float] = {}

    def put(field: str, value: float) -> None:
        scores[field] = round(min(1.0, max(0.0, value * factor)), 2)

    # E-Mail: Absenderadresse ist das stärkste Signal
    if sig.email:
        if mail and mail.from_email and sig.email.lower() == mail.from_email.lower():
            put("email", 1.0)
        elif sig.email.lower() in block.lower():
            put("email", 0.9)
        else:
            put("email", 0.6)

    # Name: im Block gefunden vs. nur aus dem Header übernommen
    if sig.full_name:
        in_block = sig.full_name.lower() in block.lower()
        base = 0.9 if in_block else 0.6
        put("full_name", base)
        if sig.first_name:
            put("first_name", base)
        if sig.last_name:
            put("last_name", base)

    if sig.academic_title:
        put("academic_title", 0.85 if sig.academic_title.lower() in block.lower()
            else 0.6)

    # Position: Keyword-Treffer macht die Zuordnung deutlich sicherer
    if sig.job_title:
        base = 0.85 if _detect_seniority(sig.job_title) else 0.6
        if _LABEL_RES["job_title"].search(_line_with(block, sig.job_title)):
            base = max(base, 0.85)
        put("job_title", base)

    if sig.department:
        base = 0.8 if _LABEL_RES["department"].search(sig.department) else 0.6
        put("department", base)

    # Organisation: Rechtsform > Domain-Marke > reine Positionsheuristik
    if sig.company:
        if _has_company_hint(sig.company):
            base = 0.9
        else:
            brand = _domain(sig.website or sig.email).split(".")[0]
            tokens = [t for t in re.split(r"[-_]", brand) if len(t) >= 3]
            company_flat = re.sub(r"[^a-z0-9]", "", sig.company.lower())
            base = 0.8 if any(t in company_flat for t in tokens) else 0.55
        put("company", base)

    # Telefonnummern: Label + E.164-Auflösung
    for fieldname in ("phone", "mobile", "fax"):
        value = getattr(sig, fieldname, "")
        if not value:
            continue
        labelled = bool(_LABEL_RES[fieldname].search(_line_with(block, value)))
        parses = bool(normalize_phone(value))
        base = 0.9 if (labelled and parses) else 0.7 if parses else 0.5
        put(fieldname, base)

    if sig.website:
        same_domain = (_domain(sig.website) and
                       _domain(sig.website) == _domain(sig.email))
        labelled = bool(_LABEL_RES["website"].search(_line_with(block, sig.website)))
        base = 0.9 if same_domain else 0.75 if labelled else 0.65
        put("website", base)

    if sig.linkedin:
        put("linkedin", 0.95)

    # Adresse: vollständige Anschrift (Straße + PLZ/Ort) ist deutlich sicherer
    if sig.address:
        has_street = bool(sig.street)
        has_plz_city = bool(sig.postal_code and sig.city) or bool(
            _PLZ_CITY.search(sig.address))
        base = 0.9 if (has_street and has_plz_city) else 0.75 if (
            has_street or has_plz_city) else 0.5
        put("address", base)
    for part in ("street", "postal_code", "city", "country"):
        if getattr(sig, part, ""):
            put(part, 0.85)

    return scores


__all__ = ["score_signature", "BLOCK_FACTORS"]
