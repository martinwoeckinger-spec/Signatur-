"""Orchestriert den Ende-zu-Ende-Workflow."""
from __future__ import annotations

from pathlib import Path

from .crm.base import CrmClient
from .email_loader import iter_email_files, load_email
from .models import ReconciliationReport
from .notifier import NotificationDraft, build_notification
from .reconciler import reconcile_contact
from .signature_extractor import extract_from_email


def run_pipeline(input_path: str | Path, crm_client: CrmClient) -> ReconciliationReport:
    """Lädt Mails, extrahiert Signaturen und gleicht gegen das CRM ab."""
    report = ReconciliationReport()
    for path in iter_email_files(input_path):
        try:
            mail = load_email(path)
        except Exception as exc:  # noqa: BLE001 - pro Datei robust bleiben
            report.skipped.append({"source": str(path), "reason": str(exc)})
            continue

        sig = extract_from_email(mail)
        if sig.is_empty():
            report.skipped.append(
                {"source": str(path), "reason": "Keine verwertbare Signatur gefunden."}
            )
            continue

        result = reconcile_contact(sig, crm_client, source=str(path))
        report.results.append(result)
    return report


def build_notification_for(
    report: ReconciliationReport, to: list[str], subject: str | None = None
) -> NotificationDraft:
    return build_notification(report, to=to, subject=subject)
