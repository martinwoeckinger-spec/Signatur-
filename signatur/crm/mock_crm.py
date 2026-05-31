"""CSV-gestütztes Mock-CRM für Demo und Tests."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from ..models import CrmContact
from .base import CrmClient

_DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "crm_mock.csv"


def _norm_name(name: str) -> str:
    return " ".join(name.lower().split())


class MockCrmClient(CrmClient):
    """Liest Kontakte aus einer CSV-Datei und sucht in-memory."""

    name = "mock"

    def __init__(self, csv_path: str | Path | None = None, **_ignored) -> None:
        self.csv_path = Path(csv_path) if csv_path else _DEFAULT_CSV
        self._by_email: dict[str, CrmContact] = {}
        self._by_name: dict[str, CrmContact] = {}
        self._load()

    def _load(self) -> None:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Mock-CRM CSV nicht gefunden: {self.csv_path}")
        with self.csv_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                contact = CrmContact(
                    crm_id=row.get("crm_id", "").strip(),
                    full_name=row.get("full_name", "").strip(),
                    first_name=row.get("first_name", "").strip(),
                    last_name=row.get("last_name", "").strip(),
                    job_title=row.get("job_title", "").strip(),
                    department=row.get("department", "").strip(),
                    company=row.get("company", "").strip(),
                    email=row.get("email", "").strip().lower(),
                    phone=row.get("phone", "").strip(),
                    mobile=row.get("mobile", "").strip(),
                    website=row.get("website", "").strip(),
                    source=self.name,
                )
                if contact.email:
                    self._by_email[contact.email] = contact
                if contact.full_name:
                    self._by_name[_norm_name(contact.full_name)] = contact

    def find_contact(
        self, email: str = "", name: str = ""
    ) -> Optional[CrmContact]:
        if email:
            hit = self._by_email.get(email.strip().lower())
            if hit:
                return hit
        if name:
            return self._by_name.get(_norm_name(name))
        return None
