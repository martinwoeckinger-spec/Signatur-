"""CSV-gestütztes Mock-CRM für Demo und Tests (inkl. Schreibpfad)."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from ..models import CrmContact, utc_now
from .base import CrmClient, CrmWriteError

_DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "crm_mock.csv"

# Spalten, die das Mock-CRM zusätzlich zur Herkunftskennzeichnung führt (FA-51)
PROVENANCE_COLUMNS = ["last_change_source", "last_change_at", "last_change_by"]

_FIELDS = ["crm_id", "full_name", "first_name", "last_name", "academic_title",
           "job_title", "department", "company", "email", "phone", "mobile",
           "website", "address", "street", "postal_code", "city", "country",
           "linkedin"]


def _norm_name(name: str) -> str:
    return " ".join(name.lower().split())


class MockCrmClient(CrmClient):
    """Liest Kontakte aus einer CSV-Datei, sucht in-memory und schreibt zurück."""

    name = "mock"
    supports_write = True

    def __init__(self, csv_path: str | Path | None = None, **_ignored) -> None:
        self.csv_path = Path(csv_path) if csv_path else _DEFAULT_CSV
        self.rows: list[dict[str, str]] = []
        self._load()

    # -- Laden/Speichern ---------------------------------------------------
    def _load(self) -> None:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Mock-CRM CSV nicht gefunden: {self.csv_path}")
        with self.csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            self.fieldnames = list(reader.fieldnames or _FIELDS)
            self.rows = [{(k or ""): (v or "").strip() for k, v in row.items()}
                         for row in reader]

    def _write(self) -> None:
        columns = list(self.fieldnames)
        for extra in PROVENANCE_COLUMNS:
            if extra not in columns:
                columns.append(extra)
        self.fieldnames = columns
        with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            for row in self.rows:
                writer.writerow({c: row.get(c, "") for c in columns})

    def _to_contact(self, row: dict[str, str]) -> CrmContact:
        return CrmContact(
            crm_id=row.get("crm_id", ""),
            full_name=row.get("full_name", ""),
            first_name=row.get("first_name", ""),
            last_name=row.get("last_name", ""),
            academic_title=row.get("academic_title", ""),
            job_title=row.get("job_title", ""),
            department=row.get("department", ""),
            company=row.get("company", ""),
            email=row.get("email", "").lower(),
            phone=row.get("phone", ""),
            mobile=row.get("mobile", ""),
            website=row.get("website", ""),
            address=row.get("address", ""),
            street=row.get("street", ""),
            postal_code=row.get("postal_code", ""),
            city=row.get("city", ""),
            country=row.get("country", ""),
            linkedin=row.get("linkedin", ""),
            source=self.name,
        )

    # -- Lesen -------------------------------------------------------------
    def find_contact(self, email: str = "", name: str = "") -> Optional[CrmContact]:
        hits = self.find_contacts(email=email, name=name)
        return hits[0] if hits else None

    def find_contacts(self, email: str = "", name: str = "",
                      domain: str = "") -> list[CrmContact]:
        """E-Mail exakt (FA-20); sonst Name (+ optional Organisationsdomain)."""
        if email:
            mail = email.strip().lower()
            hits = [r for r in self.rows if r.get("email", "").lower() == mail]
            if hits:
                return [self._to_contact(r) for r in hits]
        if name:
            key = _norm_name(name)
            hits = [r for r in self.rows if _norm_name(r.get("full_name", "")) == key]
            if domain:
                dom = domain.strip().lower().lstrip("@")
                narrowed = [r for r in hits
                            if r.get("email", "").lower().endswith("@" + dom)
                            or dom in r.get("website", "").lower()]
                if narrowed:
                    hits = narrowed
            return [self._to_contact(r) for r in hits]
        return []

    def get_contact(self, crm_id: str) -> Optional[CrmContact]:
        row = next((r for r in self.rows if r.get("crm_id") == crm_id), None)
        return self._to_contact(row) if row else None

    # -- Schreiben (FA-50, FA-51) ------------------------------------------
    def update_contact(self, crm_id: str, changes: dict[str, str], *,
                       actor: str = "", source: str = "Signature Checker",
                       ) -> dict[str, Any]:
        row = next((r for r in self.rows if r.get("crm_id") == crm_id), None)
        if row is None:
            raise CrmWriteError(f"Kontakt '{crm_id}' im Mock-CRM nicht gefunden.")
        unknown = [f for f in changes if f not in _FIELDS]
        if unknown:
            raise CrmWriteError(
                "Unbekannte Zielfelder: " + ", ".join(sorted(unknown)))
        vorher = {f: row.get(f, "") for f in changes}
        for field, value in changes.items():
            row[field] = value
            if field not in self.fieldnames:
                self.fieldnames.append(field)
        row["last_change_source"] = source
        row["last_change_at"] = utc_now()
        row["last_change_by"] = actor or "unbekannt"
        self._write()
        return {"crm_id": crm_id, "geschrieben": dict(changes), "vorher": vorher,
                "herkunft": source, "akteur": row["last_change_by"],
                "zeitpunkt": row["last_change_at"]}
