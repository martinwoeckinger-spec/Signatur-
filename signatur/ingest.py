"""Ingest-Regeln: welche E-Mails überhaupt verarbeitet werden (FA-01 … FA-05).

Die Filter arbeiten ausschließlich auf Metadaten (Absender, Header, Betreff).
Der Nachrichtentext wird nicht persistiert — gespeichert werden später nur
Metadaten und der erkannte Signaturblock (FA-03).
"""
from __future__ import annotations

import hashlib
import re

from .config import CheckerConfig
from .models import LoadedEmail

# Absenderadressen, die keine persönlichen Ansprechpartner sind (FA-04)
NOREPLY_RE = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|noreply|bounce|mailer[-_.]?daemon|"
    r"postmaster|notifications?|newsletter|info@news|automat)", re.I,
)

# Betreffmuster automatischer Antworten (deutsch/englisch)
AUTOREPLY_SUBJECT_RE = re.compile(
    r"^\s*(automatische antwort|automatic reply|auto[-\s]?reply|abwesenheit|"
    r"out of (the )?office|abwesenheitsnotiz|undeliverable|unzustellbar|"
    r"delivery status notification|read receipt|lesebestätigung)", re.I,
)

# Header, die Massen-/Systemmails kennzeichnen
BULK_HEADERS = ("list-unsubscribe", "list-id", "x-campaign-id", "x-mailer-daemon")
AUTO_HEADERS = ("auto-submitted", "x-autoreply", "x-autorespond",
                "x-auto-response-suppress")


class IngestDecision:
    """Ergebnis der Eingangsprüfung: verarbeiten oder verwerfen (mit Grund)."""

    def __init__(self, accept: bool, reason: str = "", rule: str = "") -> None:
        self.accept = accept
        self.reason = reason
        self.rule = rule

    def __bool__(self) -> bool:  # erlaubt `if decision:`
        return self.accept

    def __repr__(self) -> str:  # pragma: no cover - Debug-Hilfe
        return f"IngestDecision(accept={self.accept}, rule={self.rule!r})"

    def to_dict(self) -> dict[str, str | bool]:
        return {"accept": self.accept, "reason": self.reason, "rule": self.rule}


def sender_domain(mail: LoadedEmail) -> str:
    return (mail.from_email or "").split("@")[-1].strip().lower()


def message_key(mail: LoadedEmail) -> str:
    """Stabiler Schlüssel für die Idempotenz (FA-05).

    Bevorzugt die Message-ID; fehlt sie (z. B. bei Exporten ohne Header),
    wird ein Hash aus Absender, Datum und Betreff verwendet.
    """
    if mail.message_id:
        return mail.message_id.strip()
    raw = "|".join([mail.from_email or "", mail.date or "", mail.subject or "",
                    str(len(mail.text_body or ""))])
    return "sha1:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _domain_matches(domain: str, patterns: list[str]) -> bool:
    """Domain-Vergleich inkl. Subdomains ('example.com' matcht 'mail.example.com')."""
    domain = (domain or "").lower()
    for pattern in patterns or []:
        pat = pattern.strip().lower().lstrip("@")
        if not pat:
            continue
        if domain == pat or domain.endswith("." + pat):
            return True
    return False


def classify(mail: LoadedEmail, config: CheckerConfig) -> IngestDecision:
    """Prüft eine Mail gegen die Ingest-Regeln (ohne Idempotenz-Prüfung)."""
    if not mail.from_email:
        return IngestDecision(False, "Kein Absender ermittelbar.", "kein_absender")

    domain = sender_domain(mail)
    local = (mail.from_email or "").split("@")[0]

    if config.allowlist_domains and not _domain_matches(
            domain, config.allowlist_domains):
        return IngestDecision(
            False, f"Domain '{domain}' steht nicht auf der Allowlist.", "allowlist")

    if _domain_matches(domain, config.internal_domains):
        return IngestDecision(
            False, f"Interner Absender ({domain}).", "intern")

    if _domain_matches(domain, config.blocklist_domains):
        return IngestDecision(
            False, f"Domain '{domain}' steht auf der Blocklist.", "blocklist")

    if config.drop_noreply and NOREPLY_RE.match(local):
        return IngestDecision(
            False, f"No-Reply-/Systemadresse ({mail.from_email}).", "noreply")

    if config.drop_autoreply:
        if any(mail.header(h) for h in AUTO_HEADERS):
            return IngestDecision(False, "Automatische Antwort (Header).", "autoreply")
        if AUTOREPLY_SUBJECT_RE.match(mail.subject or ""):
            return IngestDecision(False, "Automatische Antwort (Betreff).", "autoreply")

    if config.drop_bulk:
        if any(mail.header(h) for h in BULK_HEADERS):
            return IngestDecision(False, "Newsletter/Massenmail (Header).", "bulk")
        precedence = mail.header("precedence").lower()
        if precedence in ("bulk", "list", "junk"):
            return IngestDecision(
                False, f"Newsletter/Massenmail (Precedence: {precedence}).", "bulk")

    return IngestDecision(True, "Eingehende externe Nachricht.", "ok")


def looks_like_image_signature(mail: LoadedEmail, signature_found: bool) -> bool:
    """Heuristik für Bildsignaturen (FA-16): Bilder vorhanden, aber kein Textblock."""
    return bool(mail.inline_images) and not signature_found
