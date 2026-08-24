"""Ende-zu-Ende-Verarbeitung: E-Mail → Extrakt → Match → Fall (Kapitel 7).

Fasst Ingest (FA-01…FA-05), Extraktion (FA-10…FA-16), Matching (FA-20…FA-24)
und das Relevanzregelwerk (FA-30…FA-36) zu einem Lauf zusammen. Das Ergebnis
sind Fälle im Store — geschrieben wird ins CRM erst nach menschlicher Freigabe
(FA-54, siehe `review.py`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import ingest
from .config import CheckerConfig, get_config
from .crm.base import CrmClient
from .email_loader import iter_email_files, load_email
from .matching import match_signature
from .models import (
    AuditEntry,
    Case,
    LoadedEmail,
    Signature,
    SignatureExtract,
)
from .cases import build_case, merge_into_open_case, signature_fields
from .signature_extractor import EXTRACTOR_VERSION, extract_all_signatures
from .store import CheckerStore


@dataclass
class CheckerRunReport:
    """Kennzahlen und Protokoll eines Verarbeitungslaufs."""

    gelesen: int = 0
    verarbeitet: int = 0
    verworfen: int = 0
    dubletten: int = 0
    extrakte: int = 0
    nicht_auswertbar: int = 0
    faelle_neu: list[str] = field(default_factory=list)
    faelle_aggregiert: list[str] = field(default_factory=list)
    ohne_abweichung: int = 0
    uebersprungen: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["faelle_neu_anzahl"] = len(self.faelle_neu)
        data["faelle_aggregiert_anzahl"] = len(self.faelle_aggregiert)
        return data


def _sender_signature(mail: LoadedEmail, sigs: list[Signature]) -> Signature | None:
    """Signatur des aktuellen Absenders auswählen (FA-14)."""
    if not sigs:
        return None
    if mail.from_email:
        for sig in sigs:
            if sig.email and sig.email.lower() == mail.from_email.lower():
                return sig
    return sigs[0]


def _build_extract(mail: LoadedEmail, sig: Signature | None, message_key: str,
                   auswertbar: bool = True, hinweis: str = "") -> SignatureExtract:
    """Extrakt-Datensatz — nur Metadaten und Signaturblock (FA-03)."""
    return SignatureExtract(
        message_id=message_key,
        empfangen_am=mail.date or "",
        absender_email=(sig.email if sig and sig.email else mail.from_email) or "",
        quelle=Path(mail.source).name if mail.source else "",
        betreff=mail.subject or "",
        rohtext_signatur=(sig.raw_block if sig else ""),
        felder=signature_fields(sig) if sig else {},
        konfidenz=dict(sig.confidence) if sig else {},
        verfahrensversion=(sig.extractor_version if sig else EXTRACTOR_VERSION),
        auswertbar=auswertbar,
        hinweis=hinweis,
    )


def process_email(mail: LoadedEmail, crm_client: CrmClient, store: CheckerStore,
                  config: CheckerConfig, report: CheckerRunReport) -> Case | None:
    """Verarbeitet eine einzelne Mail; liefert den erzeugten/ergänzten Fall."""
    report.gelesen += 1
    key = ingest.message_key(mail)

    if store.is_processed(key):                                    # FA-05
        report.dubletten += 1
        report.uebersprungen.append(
            {"quelle": mail.source, "grund": "Bereits verarbeitet (Message-ID)."})
        return None

    decision = ingest.classify(mail, config)                       # FA-02, FA-04
    if not decision.accept:
        report.verworfen += 1
        store.mark_processed(key, quelle=mail.source, ergebnis="verworfen",
                             regel=decision.rule)
        report.uebersprungen.append({"quelle": mail.source, "grund": decision.reason})
        return None

    sigs = extract_all_signatures(mail)                            # FA-10 … FA-14
    sig = _sender_signature(mail, sigs)

    if sig is None:
        hinweis = ("Signatur vermutlich als Bild eingebettet – nicht auswertbar."
                   if ingest.looks_like_image_signature(mail, False)
                   else "Kein auswertbarer Signaturblock gefunden.")
        store.add_extract(_build_extract(mail, None, key, auswertbar=False,
                                         hinweis=hinweis))          # FA-16
        report.nicht_auswertbar += 1
        store.mark_processed(key, quelle=mail.source, ergebnis="nicht_auswertbar")
        report.uebersprungen.append({"quelle": mail.source, "grund": hinweis})
        return None

    extract = store.add_extract(_build_extract(mail, sig, key))
    report.extrakte += 1
    report.verarbeitet += 1

    match = match_signature(sig, crm_client, config)               # FA-20 … FA-23
    neu = build_case(extract, sig, match, config, store)
    store.mark_processed(key, quelle=mail.source, ergebnis="verarbeitet",
                         extract_id=extract.id)

    if neu is None:
        report.ohne_abweichung += 1
        return None

    bestehend = (store.find_open_case(neu.dedupe_key)
                 if config.aggregate_open_cases else None)
    if bestehend is not None:                                      # FA-36
        merged = merge_into_open_case(bestehend, neu, config)
        store.put_case(merged)
        store.add_audit(AuditEntry(
            case_id=merged.id, aktion="fall_aggregiert",
            detail=f"Vorkommen: {merged.vorkommen}, Priorität: {merged.prio}",
            quelle_message_id=key, quelle_extract_id=extract.id))
        report.faelle_aggregiert.append(merged.id)
        return merged

    store.add_case(neu)
    store.add_audit(AuditEntry(
        case_id=neu.id, aktion="fall_erstellt",
        detail=f"Typ: {neu.typ.value}, Abweichungen: {len(neu.diffs)}, "
               f"Priorität: {neu.prio}",
        quelle_message_id=key, quelle_extract_id=extract.id))
    report.faelle_neu.append(neu.id)
    return neu


def run_checker(input_path: str | Path, crm_client: CrmClient,
                store: CheckerStore, config: CheckerConfig | None = None,
                ) -> CheckerRunReport:
    """Verarbeitet alle Mails eines Ordners/einer Datei."""
    cfg = config or get_config()
    report = CheckerRunReport()
    for path in iter_email_files(input_path):
        try:
            mail = load_email(path)
        except Exception as exc:  # noqa: BLE001 - pro Datei robust bleiben
            report.uebersprungen.append({"quelle": str(path), "grund": str(exc)})
            continue
        process_email(mail, crm_client, store, cfg, report)
    return report
