"""Persistenz für Extrakte, Snapshots, Fälle, Audit-Log und Suppressions.

Bewusst schlank gehalten: eine JSON-Datei, atomar geschrieben, ohne externe
Abhängigkeiten. Das reicht für die MVP-Volumina (Stufe 1) und lässt sich später
gegen eine Datenbank tauschen, ohne die aufrufenden Schichten zu ändern —
`CheckerStore` ist die einzige Stelle mit Kenntnis der Ablage.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import (
    AuditEntry,
    Case,
    CaseStatus,
    CrmSnapshot,
    SignatureExtract,
    Suppression,
    utc_now,
)
from .normalize import normalize_value

_EMPTY: dict[str, Any] = {
    "version": 1,
    "processed_messages": {},   # message_key -> Metadaten
    "extracts": [],
    "snapshots": [],
    "cases": [],
    "audit": [],
    "suppressions": [],
}


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class CheckerStore:
    """Dateibasierter Speicher; jede Schreiboperation persistiert sofort."""

    def __init__(self, path: str | Path, autosave: bool = True) -> None:
        self.path = Path(path)
        self.autosave = autosave
        self.data: dict[str, Any] = json.loads(json.dumps(_EMPTY))
        if self.path.exists():
            self.load()

    # -- Datei -----------------------------------------------------------
    def load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        for key, default in _EMPTY.items():
            self.data[key] = raw.get(key, json.loads(json.dumps(default)))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):  # pragma: no cover - nur im Fehlerfall
                os.unlink(tmp)

    def _touch(self) -> None:
        if self.autosave:
            self.save()

    # -- Idempotenz (FA-05) ----------------------------------------------
    def is_processed(self, message_key: str) -> bool:
        return message_key in self.data["processed_messages"]

    def mark_processed(self, message_key: str, **meta: Any) -> None:
        self.data["processed_messages"][message_key] = {
            "verarbeitet_am": utc_now(), **meta}
        self._touch()

    @property
    def processed_count(self) -> int:
        return len(self.data["processed_messages"])

    # -- Extrakte / Snapshots --------------------------------------------
    def add_extract(self, extract: SignatureExtract) -> SignatureExtract:
        self.data["extracts"].append(extract.to_dict())
        self._touch()
        return extract

    def get_extract(self, extract_id: str) -> Optional[dict[str, Any]]:
        return next((e for e in self.data["extracts"] if e["id"] == extract_id), None)

    @property
    def extracts(self) -> list[dict[str, Any]]:
        return list(self.data["extracts"])

    def add_snapshot(self, snapshot: CrmSnapshot) -> CrmSnapshot:
        self.data["snapshots"].append(snapshot.to_dict())
        self._touch()
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> Optional[dict[str, Any]]:
        return next((s for s in self.data["snapshots"] if s["id"] == snapshot_id), None)

    # -- Fälle -------------------------------------------------------------
    def add_case(self, case: Case) -> Case:
        self.data["cases"].append(case.to_dict())
        self._touch()
        return case

    def put_case(self, case: Case) -> Case:
        """Aktualisiert einen vorhandenen Fall (oder legt ihn an)."""
        case.aktualisiert_am = utc_now()
        for idx, existing in enumerate(self.data["cases"]):
            if existing["id"] == case.id:
                self.data["cases"][idx] = case.to_dict()
                self._touch()
                return case
        return self.add_case(case)

    def get_case(self, case_id: str) -> Optional[Case]:
        raw = next((c for c in self.data["cases"] if c["id"] == case_id), None)
        return Case.from_dict(raw) if raw else None

    def cases(self) -> list[Case]:
        return [Case.from_dict(c) for c in self.data["cases"]]

    def open_cases(self) -> list[Case]:
        offen = {CaseStatus.OFFEN, CaseStatus.IN_BEARBEITUNG, CaseStatus.KLAERUNG}
        return [c for c in self.cases() if c.status in offen]

    def find_open_case(self, dedupe_key: str) -> Optional[Case]:
        for case in self.open_cases():
            if case.dedupe_key == dedupe_key:
                return case
        return None

    # -- Audit (FA-53) -----------------------------------------------------
    def add_audit(self, entry: AuditEntry) -> AuditEntry:
        self.data["audit"].append(entry.to_dict())
        self._touch()
        return entry

    def audit(self, case_id: str = "") -> list[dict[str, Any]]:
        entries = self.data["audit"]
        return [e for e in entries if e["case_id"] == case_id] if case_id \
            else list(entries)

    # -- Suppression (FA-35) ------------------------------------------------
    def add_suppression(self, suppression: Suppression) -> Suppression:
        self.data["suppressions"].append(suppression.to_dict())
        self._touch()
        return suppression

    def suppressions(self) -> list[dict[str, Any]]:
        return list(self.data["suppressions"])

    def is_suppressed(self, crm_kontakt_id: str, feld: str, wert: str,
                      default_region: str = "DE") -> bool:
        """True, wenn genau dieser Wert für dieses Feld schon abgelehnt wurde."""
        target = normalize_value(feld, wert, default_region)
        if not target:
            return False
        now = datetime.now(timezone.utc)
        for entry in self.data["suppressions"]:
            if entry.get("feld") != feld:
                continue
            if entry.get("crm_kontakt_id") != crm_kontakt_id:
                continue
            if entry.get("abgelehnter_wert") != target:
                continue
            bis = _parse_ts(entry.get("gueltig_bis", ""))
            if bis is None or bis > now:
                return True
        return False

    # -- Aufbewahrung (DS-04) ------------------------------------------------
    def purge_expired(self, retention_days: int) -> dict[str, int]:
        """Löscht Rohsignaturen und Extrakte nach Ablauf der Aufbewahrungsfrist.

        Fälle und Audit-Einträge bleiben erhalten (Revisionssicherheit); aus den
        Extrakten wird lediglich der Rohtext entfernt.
        """
        if retention_days <= 0:
            return {"extrakte_bereinigt": 0, "extrakte_geloescht": 0}
        grenze = datetime.now(timezone.utc) - timedelta(days=retention_days)
        referenziert = {eid for case in self.data["cases"]
                        for eid in case.get("extract_ids", [])}
        bereinigt = geloescht = 0
        behalten: list[dict[str, Any]] = []
        for extract in self.data["extracts"]:
            ts = _parse_ts(extract.get("empfangen_am", "")) or \
                _parse_ts(extract.get("erstellt_am", ""))
            abgelaufen = ts is not None and ts.tzinfo is not None and ts < grenze
            if not abgelaufen:
                behalten.append(extract)
                continue
            if extract["id"] in referenziert:
                if extract.get("rohtext_signatur"):
                    extract["rohtext_signatur"] = ""
                    extract["hinweis"] = "Rohsignatur nach Aufbewahrungsfrist gelöscht."
                    bereinigt += 1
                behalten.append(extract)
            else:
                geloescht += 1
        self.data["extracts"] = behalten
        self._touch()
        return {"extrakte_bereinigt": bereinigt, "extrakte_geloescht": geloescht}

    # -- Betroffenenrechte (DS-06) -------------------------------------------
    def find_by_person(self, email: str) -> dict[str, list[dict[str, Any]]]:
        """Auskunft: alle zu einer E-Mail-Adresse gespeicherten Datensätze."""
        mail = (email or "").strip().lower()
        extracts = [e for e in self.data["extracts"]
                    if (e.get("absender_email") or "").lower() == mail]
        extract_ids = {e["id"] for e in extracts}
        cases = [c for c in self.data["cases"]
                 if (c.get("absender_email") or "").lower() == mail
                 or extract_ids.intersection(c.get("extract_ids", []))]
        case_ids = {c["id"] for c in cases}
        audit = [a for a in self.data["audit"] if a.get("case_id") in case_ids]
        return {"extracts": extracts, "cases": cases, "audit": audit}

    def delete_person(self, email: str) -> dict[str, int]:
        """Löschung: entfernt Extrakte und Fälle einer Person (Audit bleibt)."""
        found = self.find_by_person(email)
        extract_ids = {e["id"] for e in found["extracts"]}
        case_ids = {c["id"] for c in found["cases"]}
        self.data["extracts"] = [e for e in self.data["extracts"]
                                 if e["id"] not in extract_ids]
        self.data["cases"] = [c for c in self.data["cases"]
                              if c["id"] not in case_ids]
        self._touch()
        return {"extrakte": len(extract_ids), "faelle": len(case_ids)}


def open_store(path: str | Path, autosave: bool = True) -> CheckerStore:
    return CheckerStore(path, autosave=autosave)


def iter_cases(store: CheckerStore) -> Iterable[Case]:  # pragma: no cover - Komfort
    yield from store.cases()
