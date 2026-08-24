"""Laufzeit-Konfiguration des Signature Checkers (NFA-08).

Alle fachlich steuerbaren Parameter — Feld-Whitelist, Konfidenz-Schwellwerte,
Block-/Allowlists, Intervalle, Suppression-Dauer — liegen in einer JSON-Datei
und werden zur Laufzeit gelesen. Änderungen wirken ohne Deployment; ein
`reload()` bzw. ein neuer Prozessstart genügt.

Pfad-Auflösung (erste Fundstelle gewinnt):
  1. expliziter Pfad (`load_config(path)`)
  2. Umgebungsvariable `SIGNATUR_CONFIG`
  3. `config/checker.json` im Projektverzeichnis
  4. eingebaute Defaults
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "checker.json"

# Feld-Whitelist für Release 1 (Vorschlag Development, final: OP-03)
DEFAULT_FIELD_WHITELIST = [
    "job_title", "department", "company", "phone", "mobile", "website", "address",
]

DEFAULT_FIELD_LABELS = {
    "academic_title": "Akad. Titel",
    "first_name": "Vorname",
    "last_name": "Nachname",
    "full_name": "Name",
    "job_title": "Funktion/Position",
    "department": "Abteilung",
    "company": "Organisation",
    "email": "E-Mail",
    "phone": "Telefon",
    "mobile": "Mobil",
    "website": "Website",
    "address": "Adresse",
    "street": "Straße",
    "postal_code": "PLZ",
    "city": "Ort",
    "country": "Land",
    "linkedin": "LinkedIn",
}

# Gewichtung für die Fall-Priorisierung (höher = wichtiger)
DEFAULT_FIELD_WEIGHTS = {
    "company": 30, "job_title": 25, "email": 25, "mobile": 15, "phone": 15,
    "department": 10, "address": 10, "website": 5, "linkedin": 5,
}


@dataclass
class CheckerConfig:
    """Fachliche Konfiguration; Werte entsprechen den Defaults für Release 1."""

    # --- Ingest (FA-02, FA-04) ---
    internal_domains: list[str] = field(default_factory=list)
    blocklist_domains: list[str] = field(default_factory=list)
    allowlist_domains: list[str] = field(default_factory=list)
    drop_noreply: bool = True
    drop_autoreply: bool = True
    drop_bulk: bool = True

    # --- Extraktion (FA-12, FA-15) ---
    extractor: str = "rules"
    confidence_threshold: float = 0.6
    field_thresholds: dict[str, float] = field(default_factory=dict)

    # --- Matching (FA-21) ---
    min_match_confidence: float = 0.5
    allow_name_domain_fallback: bool = True

    # --- Abgleich (FA-30, FA-32, FA-35, FA-36) ---
    field_whitelist: list[str] = field(
        default_factory=lambda: list(DEFAULT_FIELD_WHITELIST))
    field_labels: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_FIELD_LABELS))
    field_weights: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_FIELD_WEIGHTS))
    default_phone_region: str = "DE"
    suppression_days: int = 365
    aggregate_open_cases: bool = True

    # --- Review/Betrieb (FA-46, FA-47, FA-50) ---
    write_mode: str = "crm"                  # "crm" = API-Schreibpfad,
                                             # "manuell" = Freigabe + Direktlink
    notification_interval_minutes: int = 240
    crm_contact_url_template: str = ""
    store_path: str = "data/checker_store.json"
    retention_days_extracts: int = 90        # DS-04, bis Freigabe vorläufig

    # Herkunft der geladenen Datei (nur informativ)
    source_path: str = ""

    # -- Zugriffshilfen --------------------------------------------------
    def threshold_for(self, field_name: str) -> float:
        return float(self.field_thresholds.get(field_name, self.confidence_threshold))

    def label_for(self, field_name: str) -> str:
        return self.field_labels.get(field_name, field_name)

    def weight_for(self, field_name: str) -> int:
        return int(self.field_weights.get(field_name, 5))

    def is_whitelisted(self, field_name: str) -> bool:
        return field_name in self.field_whitelist

    def store_file(self) -> Path:
        path = Path(self.store_path)
        return path if path.is_absolute() else ROOT / path

    def crm_link(self, crm_id: str) -> str:
        """Direktlink zum CRM-Datensatz (FA-47); leer, wenn nicht konfiguriert."""
        if not crm_id or not self.crm_contact_url_template:
            return ""
        return self.crm_contact_url_template.replace("{id}", crm_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _config_path(path: str | Path | None = None) -> Path | None:
    if path:
        return Path(path)
    env = os.environ.get("SIGNATUR_CONFIG")
    if env:
        return Path(env)
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    return None


def load_config(path: str | Path | None = None) -> CheckerConfig:
    """Lädt die Konfiguration; unbekannte Schlüssel werden ignoriert."""
    cfg_path = _config_path(path)
    if cfg_path is None or not cfg_path.exists():
        return CheckerConfig()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    known = {f for f in CheckerConfig.__dataclass_fields__}
    values = {k: v for k, v in data.items() if k in known and not k.startswith("_")}
    cfg = CheckerConfig(**values)
    cfg.source_path = str(cfg_path)
    # Labels/Gewichte aus der Datei ergänzen die Defaults, ersetzen sie nicht
    if "field_labels" in values:
        merged = dict(DEFAULT_FIELD_LABELS)
        merged.update(values["field_labels"])
        cfg.field_labels = merged
    if "field_weights" in values:
        merged_w = dict(DEFAULT_FIELD_WEIGHTS)
        merged_w.update(values["field_weights"])
        cfg.field_weights = merged_w
    return cfg


_CACHE: CheckerConfig | None = None


def get_config(path: str | Path | None = None, *, reload: bool = False) -> CheckerConfig:
    """Prozessweite Konfiguration (gecacht); `reload=True` liest neu ein."""
    global _CACHE
    if _CACHE is None or reload or path is not None:
        _CACHE = load_config(path)
    return _CACHE
