"""Gleicht extrahierte Signatur-Daten gegen einen CRM-Kontakt ab."""
from __future__ import annotations

import re

from .crm.base import CrmClient
from .models import (
    ChangeType,
    ContactReconciliation,
    CrmContact,
    Discrepancy,
    Signature,
)

# Felder, die verglichen werden: (intern, Anzeigename)
# Relevant fuer den Abgleich: Position, Firma, Adresse, Website, LinkedIn
# (Name = Identitaet, E-Mail = primaerer Schluessel); Telefon ergaenzend.
COMPARED_FIELDS = [
    ("job_title", "Position/Titel"),
    ("company", "Firma"),
    ("address", "Adresse"),
    ("website", "Website"),
    ("linkedin", "LinkedIn"),
    ("department", "Abteilung"),
    ("phone", "Telefon"),
    ("mobile", "Mobil"),
]


def _norm(value: str) -> str:
    """Normalisiert Strings für den Vergleich (Casing/Whitespace)."""
    return " ".join((value or "").lower().split())


def _norm_phone(value: str) -> str:
    """Telefonnummern auf Ziffern (inkl. führendem +) reduzieren."""
    if not value:
        return ""
    digits = re.sub(r"[^\d+]", "", value)
    return digits.lstrip("0") if not digits.startswith("+") else digits


def _values_match(field: str, a: str, b: str) -> bool:
    if field in ("phone", "mobile"):
        na, nb = _norm_phone(a), _norm_phone(b)
        if not na or not nb:
            return na == nb
        # Vergleich der letzten 7 Stellen, um Ländervorwahl-Differenzen zu tolerieren
        return na == nb or na[-7:] == nb[-7:]
    return _norm(a) == _norm(b)


def _derive_signals(sig: Signature, crm: CrmContact,
                    discrepancies: list[Discrepancy]) -> list[str]:
    """Leitet geschäftsrelevante Hinweise aus den Abweichungen ab."""
    signals: list[str] = []
    changed = {d.field for d in discrepancies
               if d.change_type == ChangeType.FIELD_CHANGED}

    if "company" in changed:
        signals.append(
            "🔁 Firmenwechsel erkannt – Kontakt prüfen (mögliche neue Opportunity "
            "beim neuen Arbeitgeber bzw. Risiko beim alten Account)."
        )
    if "job_title" in changed:
        note = "📈 Positionswechsel/Beförderung erkannt – Rolle im CRM aktualisieren."
        if sig.is_decision_maker:
            note += " Kontakt ist jetzt Entscheider:in – für Vertrieb relevant."
        signals.append(note)
    if "address" in changed:
        signals.append("📍 Adresse hat sich geändert – Stammdaten aktualisieren.")
    if "website" in changed:
        signals.append("🌐 Geänderte Website – Stammdaten aktualisieren.")
    if "linkedin" in changed:
        signals.append("🔗 LinkedIn-Profil aktualisieren.")
    if "phone" in changed or "mobile" in changed:
        signals.append("☎️ Geänderte Telefonnummer – Stammdaten aktualisieren.")
    if "department" in changed:
        signals.append("🏷️ Abteilung/Funktion hat sich geändert.")
    if sig.is_decision_maker and "job_title" not in changed:
        signals.append("⭐ Entscheider:in laut Signatur – Priorisierung im Vertrieb prüfen.")
    return signals


def reconcile_contact(sig: Signature, crm_client: CrmClient,
                      source: str = "") -> ContactReconciliation:
    """Gleicht eine Signatur gegen das CRM ab und liefert das Ergebnis."""
    result = ContactReconciliation(source=source, signature=sig)

    crm = crm_client.find_contact(email=sig.email, name=sig.full_name)
    if crm is None:
        result.matched = False
        result.crm_contact = None
        # Neuer Kontakt: alle vorhandenen Signaturfelder sind potenziell neue Daten
        for field, _label in COMPARED_FIELDS:
            val = getattr(sig, field, "")
            if val:
                result.discrepancies.append(
                    Discrepancy(field=field, change_type=ChangeType.FIELD_NEW_IN_CRM,
                                signature_value=val, crm_value="")
                )
        result.business_signals.append(
            "🆕 Kontakt nicht im CRM gefunden – als neuen Lead/Kontakt anlegen."
        )
        if sig.is_decision_maker:
            result.business_signals.append(
                "⭐ Neuer Kontakt ist laut Signatur Entscheider:in."
            )
        result.notes.append(
            f"Kein CRM-Treffer für E-Mail '{sig.email or '—'}' "
            f"/ Name '{sig.full_name or '—'}'."
        )
        return result

    result.matched = True
    result.crm_contact = crm
    result.match_key = "email" if (sig.email and sig.email == crm.email) else "name"

    for field, _label in COMPARED_FIELDS:
        sig_val = getattr(sig, field, "")
        crm_val = getattr(crm, field, "")
        if not sig_val:
            continue  # Signatur liefert nichts -> kein Hinweis
        if not crm_val:
            result.discrepancies.append(
                Discrepancy(field=field, change_type=ChangeType.FIELD_NEW_IN_CRM,
                            signature_value=sig_val, crm_value="")
            )
        elif _values_match(field, sig_val, crm_val):
            result.discrepancies.append(
                Discrepancy(field=field, change_type=ChangeType.MATCH,
                            signature_value=sig_val, crm_value=crm_val)
            )
        else:
            result.discrepancies.append(
                Discrepancy(field=field, change_type=ChangeType.FIELD_CHANGED,
                            signature_value=sig_val, crm_value=crm_val)
            )

    result.business_signals = _derive_signals(sig, crm, result.discrepancies)
    if not result.has_actionable_changes:
        result.notes.append("Signatur stimmt mit CRM überein – keine Aktion nötig.")
    return result
