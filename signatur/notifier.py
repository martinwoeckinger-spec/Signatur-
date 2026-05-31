"""Baut aus dem Abgleich-Ergebnis einen Hinweis (Text/HTML + Draft-Payload)."""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from typing import Any

from .models import ChangeType, ContactReconciliation, ReconciliationReport

_CHANGE_LABEL = {
    ChangeType.FIELD_CHANGED: "geändert",
    ChangeType.FIELD_NEW_IN_CRM: "neu (im CRM leer)",
    ChangeType.MATCH: "unverändert",
    ChangeType.NEW_CONTACT: "neuer Kontakt",
}

_FIELD_LABEL = {
    "job_title": "Position/Titel",
    "department": "Abteilung",
    "company": "Firma",
    "phone": "Telefon",
    "mobile": "Mobil",
    "website": "Website",
}


@dataclass
class NotificationDraft:
    to: list[str]
    subject: str
    text: str
    html: str

    def to_dict(self) -> dict[str, Any]:
        return {"to": self.to, "subject": self.subject,
                "text": self.text, "html": self.html}


def _contact_title(r: ContactReconciliation) -> str:
    sig = r.signature
    name = sig.full_name or sig.email or r.source
    company = f" · {sig.company}" if sig.company else ""
    return f"{name}{company}"


def _relevant_discrepancies(r: ContactReconciliation):
    return [d for d in r.discrepancies
            if d.change_type in (ChangeType.FIELD_CHANGED, ChangeType.FIELD_NEW_IN_CRM)]


# --- Text-Variante ----------------------------------------------------------

def _render_text(report: ReconciliationReport) -> str:
    s = report.to_dict()["summary"]
    lines = [
        "Signatur-/CRM-Abgleich – Hinweis",
        f"Datum: {date.today().isoformat()}",
        "",
        f"Verarbeitet: {s['processed']}  |  Neue Kontakte: {s['new_contacts']}  |  "
        f"Mit Änderungen: {s['with_changes']}  |  Übersprungen: {s['skipped']}",
        "=" * 64,
    ]
    actionable = [r for r in report.results if r.has_actionable_changes]
    if not actionable:
        lines += ["", "Keine Abweichungen gefunden – CRM ist aktuell."]
    for r in actionable:
        lines += ["", f"▶ {_contact_title(r)}", f"  Quelle: {r.source}"]
        if not r.matched:
            lines.append("  Status: NICHT im CRM gefunden (neuer Kontakt/Lead)")
        else:
            lines.append(f"  Status: im CRM gefunden (Match per {r.match_key})")
        diffs = _relevant_discrepancies(r)
        if diffs:
            lines.append("  Abweichungen:")
            for d in diffs:
                label = _FIELD_LABEL.get(d.field, d.field)
                tag = _CHANGE_LABEL[d.change_type]
                if d.change_type == ChangeType.FIELD_CHANGED:
                    lines.append(
                        f"    - {label} [{tag}]: CRM '{d.crm_value}' "
                        f"→ Signatur '{d.signature_value}'"
                    )
                else:
                    lines.append(
                        f"    - {label} [{tag}]: '{d.signature_value}'"
                    )
        for sgl in r.business_signals:
            lines.append(f"  • {sgl}")
    skipped = report.to_dict()["skipped"]
    if skipped:
        lines += ["", "Übersprungene Dateien:"]
        for item in skipped:
            lines.append(f"  - {item.get('source','?')}: {item.get('reason','?')}")
    lines += ["", "—", "Dieser Hinweis wurde automatisch erstellt (Entwurf zur Freigabe)."]
    return "\n".join(lines)


# --- HTML-Variante ----------------------------------------------------------

def _esc(v: str) -> str:
    return html.escape(v or "")


def _render_html(report: ReconciliationReport) -> str:
    s = report.to_dict()["summary"]
    parts = [
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
        "color:#1a1a1a;line-height:1.5\">",
        "<h2 style=\"margin:0 0 4px\">Signatur-/CRM-Abgleich – Hinweis</h2>",
        f"<p style=\"color:#666;margin:0 0 12px\">Datum: {date.today().isoformat()}</p>",
        "<table style=\"border-collapse:collapse;margin-bottom:16px\">"
        "<tr>"
        f"<td style=\"padding:6px 12px;background:#f3f4f6\">Verarbeitet: "
        f"<b>{s['processed']}</b></td>"
        f"<td style=\"padding:6px 12px;background:#f3f4f6\">Neue Kontakte: "
        f"<b>{s['new_contacts']}</b></td>"
        f"<td style=\"padding:6px 12px;background:#f3f4f6\">Mit Änderungen: "
        f"<b>{s['with_changes']}</b></td>"
        "</tr></table>",
    ]
    actionable = [r for r in report.results if r.has_actionable_changes]
    if not actionable:
        parts.append("<p>✅ Keine Abweichungen gefunden – CRM ist aktuell.</p>")
    for r in actionable:
        badge = ("#b91c1c", "Neuer Kontakt") if not r.matched else ("#1d4ed8", "Aktualisierung")
        parts.append(
            f"<div style=\"border:1px solid #e5e7eb;border-radius:8px;padding:12px;"
            f"margin:0 0 12px\">"
            f"<div style=\"font-weight:bold;font-size:15px\">{_esc(_contact_title(r))} "
            f"<span style=\"background:{badge[0]};color:#fff;font-size:11px;"
            f"padding:2px 8px;border-radius:10px;margin-left:6px\">{badge[1]}</span></div>"
            f"<div style=\"color:#666;font-size:12px;margin-bottom:8px\">"
            f"Quelle: {_esc(r.source)}</div>"
        )
        diffs = _relevant_discrepancies(r)
        if diffs:
            parts.append("<table style=\"border-collapse:collapse;width:100%;"
                         "font-size:13px\">"
                         "<tr style=\"background:#f9fafb\">"
                         "<th style=\"text-align:left;padding:4px 8px\">Feld</th>"
                         "<th style=\"text-align:left;padding:4px 8px\">CRM</th>"
                         "<th style=\"text-align:left;padding:4px 8px\">Signatur</th></tr>")
            for d in diffs:
                label = _FIELD_LABEL.get(d.field, d.field)
                parts.append(
                    "<tr>"
                    f"<td style=\"padding:4px 8px;border-top:1px solid #eee\">{_esc(label)}</td>"
                    f"<td style=\"padding:4px 8px;border-top:1px solid #eee;color:#9ca3af\">"
                    f"{_esc(d.crm_value) or '—'}</td>"
                    f"<td style=\"padding:4px 8px;border-top:1px solid #eee;font-weight:600\">"
                    f"{_esc(d.signature_value)}</td>"
                    "</tr>"
                )
            parts.append("</table>")
        if r.business_signals:
            parts.append("<ul style=\"margin:8px 0 0;padding-left:18px\">")
            for sgl in r.business_signals:
                parts.append(f"<li>{_esc(sgl)}</li>")
            parts.append("</ul>")
        parts.append("</div>")
    parts.append("<p style=\"color:#888;font-size:12px\">Automatisch erstellt – "
                 "Entwurf zur Freigabe.</p></div>")
    return "".join(parts)


def build_notification(
    report: ReconciliationReport,
    to: list[str],
    subject: str | None = None,
) -> NotificationDraft:
    """Erzeugt das Hinweis-Draft-Payload (Text + HTML)."""
    s = report.to_dict()["summary"]
    if subject is None:
        subject = (
            f"[Signatur-Abgleich] {s['with_changes']} Änderung(en), "
            f"{s['new_contacts']} neue(r) Kontakt(e) – {date.today().isoformat()}"
        )
    return NotificationDraft(
        to=to,
        subject=subject,
        text=_render_text(report),
        html=_render_html(report),
    )
